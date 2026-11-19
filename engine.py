"""Run isolated cases, parse strace, and grade against fixed expectations."""
import json
import os
import re
import subprocess
from time import monotonic
from urllib.request import Request, urlopen
from uuid import uuid4

from labs import LABS

IMAGE = "tracetutor-sandbox"
PREFIX = re.compile(r"^(\d+)\s+(\d+\.\d+)\s+(.*)$")
CALL = re.compile(r"^([a-zA-Z0-9_]+)\(")
RESUMED = re.compile(r"^<\.\.\. (\w+) resumed>\s?(.*)$")
ERRNO = re.compile(r"^-1 ([A-Z][A-Z0-9]+)\b")
DURATION = re.compile(r" <(\d+\.\d+)>$")


def sandbox(source, stdin, run_id):
    name = "tracetutor-" + uuid4().hex
    args = [
        "docker", "run", "--name", name, "--label", "tracetutor.run=" + run_id,
        "--network", "none", "--read-only", "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "SETUID",
        "--cap-add", "SETGID", "--cap-add", "SYS_PTRACE",
        "--cpus", "1", "--memory", "128m", "--memory-swap", "128m",
        "--pids-limit", "32", "--ulimit", "core=0", "--log-driver", "none",
        "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=32m,mode=1777",
        "-i", IMAGE, "python3", "-I", "/opt/tracetutor/sandbox.py",
    ]
    try:
        result = subprocess.run(
            args, input=json.dumps({"source": source, "input": stdin}).encode(),
            capture_output=True, timeout=15, check=False,
        )
        if result.returncode:
            raise RuntimeError("Docker 运行失败：" + result.stderr.decode(errors="replace")[:800])
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("容器未在宿主机时限内返回") from exc
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=8, check=False)


def events_from(raw):
    events, pending = [], {}
    for number, line in enumerate(raw.splitlines(), 1):
        match = PREFIX.match(line)
        if not match:
            continue
        pid, timestamp, body = match.groups()
        row = {"id": number, "pid": int(pid), "at": timestamp, "text": body, "lines": [number]}
        resumed = RESUMED.match(body)
        if resumed:
            previous = pending.pop((pid, resumed[1]), None)
            if previous:
                previous["lines"].append(number)
                previous["text"] += resumed[2]
                row = previous
            else:
                row.update(kind="partial", call=resumed[1])
                events.append(row)
                continue
        else:
            events.append(row)
        called = CALL.match(row["text"])
        if not called:
            row["kind"] = "signal" if body.startswith("---") else "exit" if body.startswith("+++") else "other"
            continue
        row.update(kind="syscall", call=called[1])
        args, sep, returned = row["text"].rpartition(") = ")
        if sep:
            timing = DURATION.search(returned)
            row["duration_us"] = round(float(timing[1]) * 1_000_000) if timing else None
            returned = DURATION.sub("", returned)
            error = ERRNO.match(returned)
            row.update(args=args[len(called[0]):], result=returned, errno=error[1] if error else None)
        else:
            unfinished = " <unfinished ...>"
            row.update(kind="pending", args=row["text"][len(called[0]):].removesuffix(unfinished))
            row["text"] = row["text"].removesuffix(unfinished)
            pending[(pid, called[1])] = row
    return events


def diagnose(lab, case, events):
    def result(code, title, confidence, evidence, hints):
        return {"code": code, "title": title, "confidence": confidence,
                "evidence": [event["id"] for event in evidence], "hints": hints}

    state = case["status"]
    if state == "passed":
        return result("passed", "通过全部用例", "confirmed", [],
                      ["试着在轨迹里找到本实验最关键的系统调用。"])
    if state == "oom":
        return result("memory_limit", "触发内存限额", "confirmed", [],
                      ["先核对输入单位与申请字节数。", "区分申请虚拟内存与实际写入页面。",
                       "对照判定中的 cgroup OOM 记录，检查分配和释放的生命周期。"])
    if state == "timeout":
        waits = [e for e in events if e.get("kind") == "pending"]
        for waiting in reversed(waits):
            if lab == "pipe" and waiting.get("call") == "read":
                pipe_id = re.search(r"pipe:\[\d+\]", waiting["text"])
                if pipe_id:
                    writes = [e for e in events if e.get("call") in {"pipe", "pipe2", "write"}
                              and pipe_id[0] in e["text"]]
                    return result("pipe_wait", "疑似在等待管道 EOF", "suspected", [*writes[-2:], waiting],
                                  ["查看最后一次未返回的读操作。", "只要还有进程持有写端，管道读完缓冲区也不会收到 EOF。",
                                   "对照同一个管道编号，检查 fork 后父子进程各自保留了哪些描述符。"])
            if lab in {"mutex", "deadlock"} and waiting.get("call") == "futex":
                return result("sync_wait", "同步等待超时", "suspected", [waiting],
                              ["定位仍在等待的线程。", "futex 等待也会出现在正常同步中，需要结合锁顺序和退出路径。",
                               "根据这条等待事件，检查哪个线程能释放对应的同步条件。"])
        return result("timeout", "超过运行时限", "insufficient", waits[-2:],
                      ["检查最后可观察到的操作。", "超时可能来自等待、循环或线程没有退出。",
                       "缩小输入并比较最后一条有返回值的事件。"])
    if lab == "file":
        errors = [e for e in events if e.get("errno") in {"EBADF", "ENOENT"}
                  and (e.get("call") in {"read", "write", "close", "lseek"} or '"/tmp/job/data.txt"' in e["text"])]
        if errors:
            return result("file_error", "文件操作返回错误", "confirmed", errors[-2:],
                          ["查找失败的系统调用和 errno。", "文件描述符只有在打开成功且关闭之前才有效。",
                           "对照证据中的参数，检查错误值如何传到下一次读写。"])
    titles = {"compile_error": "编译失败", "wrong_output": "输出与测试预期不同",
              "runtime_error": "程序异常退出", "output_limit": "输出或轨迹达到限制", "missing_behavior": "缺少实验要求的系统调用",
              "trace_error": "轨迹采集未完成"}
    return result(state, titles.get(state, "缺少可定位证据"), "insufficient", [],
                  ["从第一个失败用例开始。", "先核对判定条件，再检查程序状态。",
                   "查看判定中的编译或运行输出，确认最早出现的差异。"])


def evaluate(lab_key, source, run_id, progress=lambda _: None):
    lab = LABS[lab_key]
    results = []
    for case in lab["cases"]:
        progress("running")
        output = sandbox(source, case["stdin"], run_id)
        compile_log = output["compile"]
        runtime = output.get("run", {})
        compile_code = compile_log["code"]
        case_result = {"name": case["name"], "expected": case["expected"], "compile": compile_log}
        if compile_code != 0:
            case_result["status"] = "compile_error"
            results.append(case_result)
            break

        raw = runtime.pop("trace")
        case_result.update(runtime)
        case_result["trace"] = raw
        case_result["status"] = (
            "oom" if runtime["oom"] else
            "timeout" if runtime["timeout"] else
            "output_limit" if runtime["truncated"] or runtime["trace_truncated"] else
            "trace_error" if 'execve("/tmp/job/task"' not in raw else
            "runtime_error" if runtime["code"] != 0 else
            "wrong_output" if runtime["stdout"] != case["expected"] else "passed"
        )
        if case_result["status"] == "passed":
            observed = {event["call"] for event in events_from(raw)
                        if event["kind"] == "syscall" and event.get("errno") is None}
            if any(not observed.intersection(group) for group in lab["required"]):
                case_result["status"] = "missing_behavior"
        results.append(case_result)

    progress("analyzing")
    evidence_case = next((i for i, case in enumerate(results) if case["status"] != "passed"), 0)
    evidence = results[evidence_case]
    evidence_events = events_from(evidence.get("trace", ""))
    analysis = diagnose(lab_key, evidence, evidence_events)
    return {
        "cases": results, "total": len(lab["cases"]),
        "passed": sum(case["status"] == "passed" for case in results),
        "evidence_case": evidence_case, "diagnosis": analysis,
    }


def ai_hints(lab_key, diagnosis, events):
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return {"source": "rules", "reason": "未配置模型 API", "hints": diagnosis["hints"]}
    if diagnosis["confidence"] == "insufficient" or diagnosis["code"] == "passed":
        return {"source": "rules", "reason": "当前结果适用规则提示", "hints": diagnosis["hints"]}

    selected = [e for e in events if e["id"] in diagnosis["evidence"]]
    context = {"lab": LABS[lab_key]["title"], "finding": diagnosis["title"],
               "confidence": diagnosis["confidence"], "guidance": diagnosis["hints"],
               "evidence": [{k: e.get(k) for k in ("id", "pid", "kind", "call", "errno")}
                            for e in selected]}
    payload = {
        "model": "deepseek-flash", "thinking": {"type": "disabled"}, "temperature": 0.2,
        "max_tokens": 450, "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是中文操作系统助教。根据提供的诊断和证据，生成三条简短分层提问。"
             "依次为观察方向、原理推理、证据定位。保留置信边界。禁止源代码、修复步骤及新事实。"
             '仅输出 JSON 对象 {"hints":["问题","问题","问题"],"evidence":[已有事件编号]}。'},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
    }
    started = monotonic()
    try:
        request = Request("https://api.deepseek.com/chat/completions",
                          data=json.dumps(payload).encode(),
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urlopen(request, timeout=8) as response:
            completion = json.loads(response.read(32_768))
        data = json.loads(completion["choices"][0]["message"]["content"])
        hints, refs = data["hints"], data["evidence"]
        if not (isinstance(hints, list) and len(hints) == 3 and
                all(isinstance(h, str) and 5 <= len(h) <= 140 and
                    h.endswith(("？", "?")) and not re.search(r"[\x00-\x1f\x60{};]", h) for h in hints) and
                isinstance(refs, list) and all(type(ref) is int for ref in refs) and
                set(refs) == set(diagnosis["evidence"])):
            raise ValueError("模型提示或证据引用不符合约定")
        return {"source": "ai", "hints": hints, "evidence": refs, "model": completion["model"],
                "usage": completion.get("usage"), "duration_ms": round((monotonic() - started) * 1000)}
    except (ValueError, OSError, KeyError, IndexError, TypeError):
        return {"source": "rules", "reason": "模型不可用或反馈校验失败", "hints": diagnosis["hints"]}
