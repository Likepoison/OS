import concurrent.futures
from io import BytesIO
import json
import os
import subprocess
from unittest import TestCase
from unittest.mock import patch

from engine import ai_hints, evaluate, events_from, sandbox
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
