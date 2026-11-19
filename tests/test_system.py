import concurrent.futures
from io import BytesIO
import json
import os
import subprocess
from unittest import TestCase
from unittest.mock import patch

from engine import ai_hints, evaluate, events_from, pipe_wait, sandbox
from labs import LABS, sample


class Evaluation(TestCase):
    def test_resumed_event(self):
        trace = (
            '12  1.001200 read(3<pipe:[1]>,  <unfinished ...>\n'
            '14  1.001300 write(4<pipe:[1]>, "x", 1) = 1 <0.000010>\n'
            '12  1.001400 <... read resumed>"x", 1) = 1 <0.000220>\n'
            '14  1.001500 close(8) = -1 EBADF (Bad file descriptor) <0.000001>\n'
        )
        merged, _, failed = events_from(trace)
        self.assertEqual((merged["id"], merged["lines"], merged["duration_us"]), (1, [1, 3], 220))
        self.assertEqual(failed["errno"], "EBADF")

    def test_pipe_accounts_for_closing_and_inherited_descriptors(self):
        raw = (
            "10  1.000001 pipe2([3, 4], 0) = 0\n"
            "10  1.000002 clone(flags=SIGCHLD) = 11\n"
            "10  1.000003 close(4) = 0\n"
            "10  1.000004 read(3,  <unfinished ...>\n"
        )
        events = events_from(raw)
        _, owners = pipe_wait(events, events[3])
        self.assertEqual(owners, [(11, 4)])
        events = events_from(raw + "11  1.000005 close(4) = 0\n")
        self.assertIsNone(pipe_wait(events, events[3]))

    def test_sandbox_uses_separate_identity(self):
        code = '#include <unistd.h>\n#include <stdio.h>\n'
        code += 'int main(void){printf("%ld\\n",(long)getuid());return access("/tmp/control/trace", W_OK)==0;}'
        run = sandbox(code, "", "identity")["run"]
        self.assertEqual(run["stdout"], "65534\n")
        self.assertEqual(run["code"], 0)
        self.assertIn('execve("/tmp/job/task"', run["trace"])

    def test_correct_faulty_and_boundary_cases(self):
        findings = {"pipe": "pipe_wait", "file": "file_error", "mutex": "sync_wait",
                    "memory": "memory_limit", "schedule": "wrong_output", "deadlock": "sync_wait"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as jobs:
            for key, lab in LABS.items():
                with self.subTest(experiment=key):
                    good = jobs.submit(evaluate, key, sample(lab), f"good-{key}")
                    bad = jobs.submit(evaluate, key, sample(lab, broken=True), f"bad-{key}")
                    passed, failed = good.result(), bad.result()
                    self.assertEqual(passed["passed"], 2, [(c["status"], c.get("stderr")) for c in passed["cases"]])
                    self.assertLess(failed["passed"], 2)
                    analysis = failed["diagnosis"]
                    case = failed["cases"][failed["evidence_case"]]
                    self.assertEqual(analysis["code"], findings[key], case.get("trace", "")[-2600:])
                    ids = {event["id"] for event in events_from(case.get("trace", ""))}
                    self.assertTrue(set(analysis["evidence"]).issubset(ids))
        remaining = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=tracetutor.run"])
        self.assertEqual(remaining, b"")

    def test_rejects_expected_output_without_memory_or_thread_behavior(self):
        memory = '#include <stdio.h>\nint main(void){size_t n; scanf("%zu",&n); printf("%zu\\n",n);}'
        threads = """
#include <pthread.h>
#include <stdio.h>
static void *empty(void *arg) { return arg; }
int main(void) {
    pthread_t a, b;
    int n;
    scanf("%d", &n);
    pthread_create(&a, NULL, empty, NULL);
    pthread_create(&b, NULL, empty, NULL);
    pthread_join(a, NULL);
    pthread_join(b, NULL);
    printf("worker A\\nworker B\\n%d\\n", 2*n);
}
"""
        for lab, source in [("memory", memory), ("mutex", threads), ("deadlock", threads)]:
            with self.subTest(lab=lab):
                report = evaluate(lab, source, f"behavior-{lab}")
                self.assertEqual(report["passed"], 0)
                self.assertEqual([case["status"] for case in report["cases"]], ["missing_behavior"] * 2)

    def test_cleanup_failure_is_a_platform_error(self):
        def docker(args, **_kwargs):
            if args[1] == "run":
                return subprocess.CompletedProcess(args, 0, b"{}", b"")
            return subprocess.CompletedProcess(args, 1, b"", b"conflict: cannot remove running container")

        with patch("engine.subprocess.run", side_effect=docker):
            with self.assertRaisesRegex(RuntimeError, r"容器清理失败（tracetutor-[0-9a-f]+）"):
                sandbox("int main(void){}", "", "cleanup-failure")

    def test_pipe_evidence_on_held_out_cases(self):
        source = sample(LABS["pipe"]).replace(
            "close(fd[1]);  /* Parent write end */",
            "int extra = dup(fd[1]); if (extra < 0) return 2; close(fd[1]);",
        )
        report = evaluate("pipe", source, "duplicate-write-end")
        self.assertEqual(report["diagnosis"]["code"], "pipe_wait")
        self.assertGreaterEqual(len(report["diagnosis"]["evidence"]), 2)
        unknown = evaluate("pipe", "int main(void){for(;;){}}", "unrelated-timeout")
        self.assertEqual(unknown["diagnosis"]["code"], "timeout")
        self.assertEqual(unknown["diagnosis"]["confidence"], "insufficient")

    def test_compile_and_output_error(self):
        invalid = evaluate("pipe", "int main( {", "invalid")
        self.assertEqual(invalid["cases"][0]["status"], "compile_error")
        noisy = '#include <stdio.h>\nint main(void){for (;;) puts("bounded output");}'
        result = evaluate("pipe", noisy, "output")
        self.assertEqual(result["cases"][0]["status"], "output_limit")
        self.assertLessEqual(len(result["cases"][0]["stdout"]), 256 * 1024)

    def test_model_validates_evidence(self):
        analysis = {"confidence": "suspected", "code": "pipe_wait", "title": "等待",
                    "hints": ["规则提示"], "evidence": [7]}
        context = [{"id": 7, "pid": 3, "kind": "pending", "call": "read"}]
        payload = {"model": "test-double", "choices": [{"message": {"content": json.dumps({
            "hints": ["读操作返回了吗？", "什么时候读到 EOF？", "哪个调用仍在等待？"], "evidence": [7],
        })}}]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fixture"}):
            with patch("engine.urlopen", return_value=BytesIO(json.dumps(payload).encode())):
                self.assertEqual(ai_hints("pipe", analysis, context)["source"], "ai")
            payload["choices"][0]["message"]["content"] = '{"hints":[],"evidence":[99]}'
            with patch("engine.urlopen", return_value=BytesIO(json.dumps(payload).encode())):
                self.assertEqual(ai_hints("pipe", analysis, context)["source"], "rules")
