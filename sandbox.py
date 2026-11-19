"""Trusted container supervisor. Student code runs under UID 65534."""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from time import monotonic

LIMIT = 256 * 1024
SAFE_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/tmp/job"}


def oom_kills():
    values = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines())
    return int(values["oom_kill"])


def file_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))


def invoke(command, timeout, label, input_data=b""):
    start = monotonic()
    stdout = Path(f"/tmp/control/{label}.out")
    stderr = Path(f"/tmp/control/{label}.err")
    before = oom_kills()
    with stdout.open("wb") as out, stderr.open("wb") as err:
        try:
            code = subprocess.run(
                command, input=input_data, stdout=out, stderr=err, timeout=timeout,
                env=SAFE_ENV, cwd="/tmp/job", preexec_fn=file_limit, check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            code = None
    return {
        "code": code, "timeout": code is None, "oom": oom_kills() > before,
        "duration_ms": round((monotonic() - start) * 1000),
        "stdout": stdout.read_bytes()[:LIMIT].decode("utf-8", errors="replace"),
        "stderr": stderr.read_bytes()[:LIMIT].decode("utf-8", errors="replace"),
        "truncated": max(stdout.stat().st_size, stderr.stat().st_size) >= LIMIT,
    }


def run(request):
    os.umask(0o077)
    Path("/tmp/control").mkdir(mode=0o700)
    work = Path("/tmp/job")
    work.mkdir(mode=0o755)
    source = work / "task.c"
    source.write_text(request["source"], encoding="utf-8")
    source.chmod(0o644)
    os.chown(work, 65534, 65534)

    compile_result = invoke(
        ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups",
         "gcc", "-std=c11", "-Wall", "-Wextra", "-O1", "-pthread", "task.c", "-o", "task"],
        5, "compile",
    )
    if compile_result["code"] != 0:
        return {"compile": compile_result}

    trace = Path("/tmp/control/trace")
    run_result = invoke(
        ["strace", "-f", "-ttt", "-T", "-yy", "-s", "96", "--kill-on-exit",
         "-e", "trace=%process,%desc,%memory,futex,clock_nanosleep,sched_yield,openat",
         "-o", str(trace), "-u", "nobody", "/tmp/job/task"],
        2, "run", request["input"].encode(),
    )
    raw = trace.read_bytes() if trace.exists() else b""
    run_result["trace"] = raw[:LIMIT].decode("utf-8", errors="replace")
    run_result["trace_truncated"] = len(raw) >= LIMIT or run_result["timeout"]
    return {"compile": compile_result, "run": run_result}


if __name__ == "__main__":
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=True))
