import concurrent.futures
from io import BytesIO
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import app
from engine import ai_hints, diagnose, evaluate, events_from, observed_behavior, pipe_wait, sandbox
from labs import LABS, sample


class Evaluation(TestCase):
    def test_diagnosis_on_independent_traces(self):
        launch = '20 execve("/tmp/job/task", ["/tmp/job/task"], 0x7f /* 3 vars */) = 0'
        created = "20 clone(flags=CLONE_THREAD|CLONE_FILES) = 21"
        waiting = "21 futex(0x2000, FUTEX_WAIT_PRIVATE, 2, NULL <unfinished ...>"
        joined = "20 futex(0x1000, FUTEX_WAIT_BITSET|FUTEX_CLOCK_REALTIME, 21, NULL <unfinished ...>"
        closed = "20 close(3</tmp/job/notes.txt>) = 0"
        invalid_fd = "20 lseek(3, 0, SEEK_SET) = -1 EBADF (Bad file descriptor)"
        file_probe = '20 openat(AT_FDCWD</tmp/job>, "optional.txt", O_RDONLY) = -1 ENOENT (No such file or directory)'
        fatal = "20 +++ killed by SIGSEGV +++"
        fixtures = [
            ("file-use-after-close", "file", "runtime_error", [closed, invalid_fd], "file_error", "confirmed", [2, 3]),
            ("file-missing", "file", "runtime_error", [file_probe], "file_error", "confirmed", [2]),
            ("unrelated-fd", "file", "runtime_error", [invalid_fd], "runtime_error", "insufficient", []),
            ("recovered-file-probe", "file", "wrong_output", [file_probe], "wrong_output", "insufficient", []),
            ("worker-blocked", "mutex", "timeout", [created, waiting, joined], "sync_wait", "suspected", [3]),
            ("main-join-only", "deadlock", "timeout", [created, joined], "timeout", "insufficient", [3]),
            ("worker-wake", "mutex", "timeout", [created, waiting.replace("FUTEX_WAIT_PRIVATE", "FUTEX_WAKE_PRIVATE")],
             "timeout", "insufficient", []),
            ("single-process-signal", "memory", "runtime_error", [fatal], "signal_exit", "confirmed", [2]),
            ("earlier-file-error-and-fatal-signal", "file", "runtime_error", [closed, invalid_fd, fatal],
             "signal_exit", "confirmed", [4]),
            ("child-signal-handled", "pipe", "runtime_error",
             ["20 clone(flags=SIGCHLD) = 21", "21 +++ killed by SIGSEGV +++", "20 +++ exited with 2 +++"],
             "runtime_error", "insufficient", []),
            ("caught-signal", "memory", "runtime_error",
             ["20 --- SIGSEGV {si_signo=SIGSEGV, si_code=SI_TKILL} ---", "20 +++ exited with 2 +++"],
             "runtime_error", "insufficient", []),
            ("no-trace", "pipe", "timeout", [], "timeout", "insufficient", []),
            ("external-pipe", "pipe", "timeout",
             ["20 read(0<pipe:[99]>,  <unfinished ...>"], "timeout", "insufficient", [2]),
            ("timeout-outweighs-signal", "memory", "timeout", [fatal], "timeout", "insufficient", []),
        ]
        for name, lab, state, body, code, confidence, refs in fixtures:
            with self.subTest(fixture=name):
                raw = "\n".join(f"{pid} 1.{i:06d} {text}" for i, row in enumerate([launch, *body], 1)
                                for pid, _, text in [row.partition(" ")])
                analysis = diagnose(lab, {"status": state}, events_from(raw))
                self.assertEqual((analysis["code"], analysis["confidence"], analysis["evidence"]),
                                 (code, confidence, refs))

    def test_failed_trace_launch_is_not_a_student_failure(self):
        runtime = {"code": 1, "oom": False, "timeout": False, "truncated": False,
                   "trace_truncated": False, "stdout": "",
                   "trace": '12 1.000001 execve("/tmp/job/task", [], []) = -1 EACCES (Permission denied)'}
        with patch("engine.sandbox", side_effect=lambda *_: {"compile": {"code": 0}, "run": runtime.copy()}):
            report = evaluate("pipe", "int main(void){}", "failed-trace")
        self.assertEqual(report["diagnosis"]["code"], "trace_error")
        self.assertEqual(len(report["cases"]), 1)
        self.assertFalse(report["scored"])

    def test_reports_compile_timeout_separately(self):
        with patch("engine.sandbox", return_value={"compile": {"code": None, "timeout": True}}):
            report = evaluate("pipe", "int main(void){}", "compile-timeout")
        self.assertEqual(report["diagnosis"]["code"], "compile_timeout")
        self.assertTrue(report["scored"])

    def test_file_behavior_requires_reading_the_written_file(self):
        lines = [
            '20 1.000001 openat(AT_FDCWD</tmp/job>, "notes.txt", O_CREAT|O_RDWR, 0600) = 3</tmp/job/notes.txt>',
            '20 1.000002 read(0<pipe:[2]>, "x", 1) = 1',
            '20 1.000003 write(3</tmp/job/notes.txt>, "x", 1) = 1',
            '20 1.000004 lseek(3</tmp/job/notes.txt>, 0, SEEK_SET) = 0',
            '20 1.000005 read(3</tmp/job/notes.txt>, "x", 1) = 1',
        ]
        case = LABS["file"]["cases"][0]
        self.assertTrue(observed_behavior("file", case, events_from("\n".join(lines))))
        self.assertFalse(observed_behavior("file", case, events_from("\n".join(lines[:-1]))))

    def test_trace_failure_is_stored_as_unscored(self):
        report = {"scored": False, "evidence_case": 0, "cases": [{"trace": ""}],
                  "diagnosis": {"code": "trace_error", "hints": ["检查采集服务"]}}
        with TemporaryDirectory() as temp, patch.object(app, "DATABASE", Path(temp) / "test.sqlite3"):
            app.initialize()
            with app.database() as conn:
                conn.execute("INSERT INTO runs (id,lab,created,state) VALUES ('test','pipe','0','queued')")
            self.assertTrue(app.SLOTS.acquire(blocking=False))
            with patch.object(app, "evaluate", return_value=report):
                app.run_job("test", "pipe", "", False)
            with app.database() as conn:
                run = conn.execute("SELECT * FROM runs WHERE id='test'").fetchone()
                self.assertEqual((run["state"], run["outcome"]), ("platform_error", "trace_error"))
                self.assertFalse(json.loads(run["result"])["scored"])

    def test_diagnosis_against_independent_programs(self):
        programs = [
            ("file", '#include <unistd.h>\nint main(void){lseek(90,0,SEEK_SET);return 2;}',
             "runtime_error", "insufficient"),
            ("file", '#include <fcntl.h>\nint main(void){return open("missing-case.txt",O_RDONLY)<0;}',
             "file_error", "confirmed"),
            ("mutex", """
                #include <pthread.h>
                static void *spin(void *p) { for (;;) {} return p; }
                int main(void) {
                    pthread_t worker;
                    if (pthread_create(&worker, 0, spin, 0)) return 2;
                    return pthread_join(worker, 0);
                }
                """, "timeout", "insufficient"),
            ("memory", '#include <stdlib.h>\nint main(void){abort();}', "signal_exit", "confirmed"),
            ("pipe", """
                #include <signal.h>
                #include <sys/wait.h>
                #include <unistd.h>
                int main(void) {
                    pid_t child = fork();
                    if (child == 0) raise(SIGABRT);
                    if (child > 0) waitpid(child, 0, 0);
                    return 2;
                }
                """, "runtime_error", "insufficient"),
        ]
        for i, (lab, source, code, confidence) in enumerate(programs):
            with self.subTest(lab=lab, expected=code):
                report = evaluate(lab, source, f"independent-{i}")
                finding = report["diagnosis"]
                case = report["cases"][report["evidence_case"]]
                events = {event["id"]: event for event in events_from(case["trace"])}
                self.assertEqual((finding["code"], finding["confidence"]), (code, confidence),
                                 case["trace"][-2000:])
                raw_lines = case["trace"].splitlines()
                for ref in finding["evidence"]:
                    self.assertTrue(all(raw_lines[line-1] for line in events[ref]["lines"]))
                if code == "signal_exit":
                    self.assertIn("SIGABRT", finding["title"])
                if code == "file_error":
                    self.assertEqual(events[finding["evidence"][0]]["errno"], "ENOENT")

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

    def test_padded_dup_result_preserves_pipe_write_end(self):
        events = events_from(
            "16  1.000001 pipe2([3, 4], 0) = 0\n"
            "16  1.000002 dup(4)          = 5 <0.000019>\n"
            "16  1.000003 close(4)        = 0 <0.000052>\n"
            "16  1.000004 read(3, "
        )
        self.assertEqual((events[1]["kind"], events[1]["result"]), ("syscall", "5"))
        _, owners = pipe_wait(events, events[-1])
        self.assertEqual(owners, [(16, 5)])

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
        hints = ["读操作返回了吗？", "什么时候读到 EOF？", "哪个调用仍在等待？"]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fixture"}):
            for refs, expected in [([7], "ai"), ([99], "rules"), ([7, 7], "rules")]:
                with self.subTest(refs=refs):
                    content = json.dumps({"hints": hints, "evidence": refs})
                    payload = {"model": "test-double", "choices": [{"message": {"content": content}}]}
                    with patch("engine.urlopen", return_value=BytesIO(json.dumps(payload).encode())):
                        self.assertEqual(ai_hints("pipe", analysis, context)["source"], expected)
            with patch("engine.urlopen", side_effect=TimeoutError):
                self.assertEqual(ai_hints("pipe", analysis, context)["source"], "rules")
            with patch("engine.urlopen") as call:
                unknown = {**analysis, "confidence": "insufficient"}
                self.assertEqual(ai_hints("pipe", unknown, context)["source"], "rules")
                call.assert_not_called()
