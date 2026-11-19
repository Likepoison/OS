"""Run isolated cases, parse strace, and grade against fixed expectations."""
import json
import os
import re
import subprocess
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from labs import LABS

IMAGE = "tracetutor-sandbox"
PREFIX = re.compile(r"^(\d+)\s+(\d+\.\d+)\s+(.*)$")
CALL = re.compile(r"^([a-zA-Z0-9_]+)\(")
RESUMED = re.compile(r"^<\.\.\. (\w+) resumed>\s?(.*)$")
ERRNO = re.compile(r"^-1 ([A-Z][A-Z0-9]+)\b")
DURATION = re.compile(r" <(\d+\.\d+)>$")
FUTEX_WAIT = re.compile(r"[^,]+, FUTEX_WAIT(?:_BITSET)?(?:_PRIVATE)?(?:\|[^,]+)?,")
FATAL_EXIT = re.compile(r"^\+\+\+ killed by (SIG[A-Z0-9]+)(?: \(core dumped\))? \+\+\+$")
TEMP_FD = re.compile(r'^(\d+)<(/tmp/[^>]+)>(?:,|$)')
TEMP_OPEN = re.compile(r'^(?:[^,]+, )?"/tmp/|^AT_FDCWD</tmp/job>, "(?!/|\.\./)[^"]+')


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
            raise RuntimeError("Docker 运行失败：" + result.stderr.decode(errors="replace")[-1400:])
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("容器未在宿主机时限内返回") from exc
    finally:
        try:
            cleanup = subprocess.run(["docker", "rm", "-f", name],
                                     capture_output=True, timeout=8, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise RuntimeError(f"容器清理失败（{name}）") from exc
        if cleanup.returncode:
            error = cleanup.stderr.decode(errors="replace").strip()
            if error not in {f"No such container: {name}",
                             f"Error response from daemon: No such container: {name}"}:
                raise RuntimeError(f"容器清理失败（{name}）：{error[-600:]}")


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
        completed = re.fullmatch(r"(.*)\)\s+=\s+(.*)", row["text"])
        if completed:
            args, returned = completed.groups()
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


def pipe_wait(events, waiting):
    """Infer tracked pipe ownership within the observed portion of one process tree."""
    tables = {}
    pipe_events = {}
    for event in events:
        pid, kind = event["pid"], event["kind"]
        if kind == "exit":
            tables.pop(pid, None)
            continue
        if kind != "syscall" or event.get("errno"):
            continue
        fds = tables.setdefault(pid, {})
        call = event["call"]
        first = re.match(r"(\d+)", event.get("args", ""))
        returned = re.match(r"(\d+)", event.get("result", ""))
        if call in {"pipe", "pipe2"} and event.get("result") == "0":
            pair = re.match(r"\[(\d+)(?:<[^>]+>)?,\s*(\d+)(?:<[^>]+>)?\]", event["args"])
            if pair:
                pipe_events[event["id"]] = event
                fds[int(pair[1])] = (event["id"], "read")
                fds[int(pair[2])] = (event["id"], "write")
        elif call in {"clone", "clone3", "fork", "vfork"} and returned and int(returned[1]):
            tables[int(returned[1])] = fds if "CLONE_FILES" in event["args"] else fds.copy()
        elif call == "close" and first and event.get("result") == "0":
            fds.pop(int(first[1]), None)
        elif first and returned and (call in {"dup", "dup2", "dup3"} or
                                     (call == "fcntl" and "F_DUPFD" in event["args"])):
            entry = fds.get(int(first[1]))
            if entry:
                fds[int(returned[1])] = entry
            else:
                fds.pop(int(returned[1]), None)
    descriptor = re.match(r"(\d+)", waiting.get("args", ""))
    if not descriptor:
        return None
    reader = tables.get(waiting["pid"], {}).get(int(descriptor[1]))
    if not reader or reader[1] != "read":
        return None
    owners = sorted({(pid, fd) for pid, fds in tables.items() for fd, entry in fds.items()
                     if entry == (reader[0], "write")})
    if not owners:
        return None
    return pipe_events[reader[0]], owners


def task_entry(events):
    return next((e for e in events if e.get("call") == "execve"
                 and e.get("args", "").startswith('"/tmp/job/task",')
                 and e.get("result") == "0"), None)


def worker_ids(events):
    return {int(e["result"]) for e in events if e["kind"] == "syscall" and e["call"] in {"clone", "clone3"}
            and "CLONE_THREAD" in e["args"] and e.get("result", "").isdigit() and int(e["result"]) > 0}


def file_failure(events):
    previous_calls = {}
    for event in events:
        if event["kind"] != "syscall":
            continue
        previous = previous_calls.get(event["pid"])
        previous_calls[event["pid"]] = event
        call, args, error = event["call"], event["args"], event["errno"]
        if not error:
            continue
        if call in {"open", "openat", "openat2"} and TEMP_OPEN.match(args):
            return [event]
        if call in {"read", "write", "close", "lseek", "pread64", "pwrite64"}:
            if TEMP_FD.match(args):
                return [event]
            if error == "EBADF" and previous and previous["call"] == "close" and previous["result"] == "0":
                closed = TEMP_FD.match(previous["args"])
                if closed and (args == closed[1] or args.startswith(closed[1] + ",")):
                    return [previous, event]
    return []


def diagnose(lab, case, events):
    def result(code, title, confidence, evidence, hints):
        return {"code": code, "title": title, "confidence": confidence,
                "evidence": [event["id"] for event in evidence], "hints": hints}

    state = case["status"]
    if state == "passed":
        return result("passed", "通过全部用例", "confirmed", [],
                      ["试着在轨迹里找到本实验最关键的系统调用。"])
    if state == "oom":
        finding = result("memory_limit", "触发内存限额", "confirmed", [],
                         ["先核对输入单位与申请字节数。", "区分申请虚拟内存与实际写入页面。",
                          "对照判定中的 cgroup OOM 记录，检查分配和释放的生命周期。"])
        finding["detail"] = f"cgroup memory.events 记录 {case['oom_kills']} 次 OOM 终止。"
        return finding
    if state == "timeout":
        waits = [e for e in events if e["kind"] == "pending"
                 and (e["call"] != "futex" or FUTEX_WAIT.match(e["args"]))]
        workers = worker_ids(events) if lab in {"mutex", "deadlock"} else set()
        for waiting in reversed(waits):
            if lab == "pipe" and waiting.get("call") == "read":
                tracked = pipe_wait(events, waiting)
                if tracked:
                    opened, owners = tracked
                    finding = result("pipe_wait", "疑似在等待管道 EOF", "suspected", [opened, waiting],
                                     ["查看哪一个读操作在超时前还没返回。",
                                      "缓冲区读空后，什么时候才能收到 EOF？",
                                      "结合管道创建和等待事件，检查哪些进程仍可能持有写端。"])
                    finding["detail"] = "按已采集轨迹推断，仍可能持有写端：" + "、".join(
                        f"PID {pid} / FD {fd}" for pid, fd in owners[:4]
                    )
                    return finding
            if waiting["pid"] in workers and waiting["call"] == "futex":
                return result("sync_wait", "工作线程的同步等待超时", "suspected", [waiting],
                              ["哪个工作线程仍未返回？", "这次等待可能对应哪一种同步条件？",
                               "根据等待调用，哪个线程应当改变对应的同步条件？"])
        return result("timeout", "超过运行时限", "insufficient", waits[-2:],
                      ["检查最后可观察到的操作。", "超时可能来自等待、循环或线程没有退出。",
                       "缩小输入并比较最后一条有返回值的事件。"])
    if state == "runtime_error":
        entry = task_entry(events)
        if entry:
            for ending in reversed(events):
                if ending["pid"] != entry["pid"] or ending["kind"] != "exit":
                    continue
                if fatal := FATAL_EXIT.fullmatch(ending["text"]):
                    return result("signal_exit", f"主进程因 {fatal[1]} 终止", "confirmed", [ending],
                                  ["主进程最后收到了哪个信号？", "什么条件会触发这个信号？",
                                   "从退出事件往前看，能找到最后完成的相关调用吗？"])
                break
        if lab == "file" and (errors := file_failure(events)):
            return result("file_error", "实验文件操作返回错误", "confirmed", errors,
                          ["哪一个文件调用返回了 errno？", "描述符在什么条件下才有效？",
                           "从关联事件回看文件路径或描述符的状态发生了什么变化？"])
    if state == "trace_error":
        return result("trace_error", "未采集到程序启动轨迹", "confirmed", [],
                      ["重新运行一次，确认新任务能启动。", "轨迹缺失时无法核对实验行为。",
                       "若再次出现，请保留本次记录并检查沙箱采集服务。"])
    if state == "compile_timeout":
        return result("compile_timeout", "编译超过时限", "confirmed", [],
                      ["编译输出中最后报告了什么？", "编译阶段可能因源码展开内容过多而耗时。",
                       "减少输入源码，逐步定位造成编译耗时的部分。"])
    titles = {"compile_error": "编译失败", "wrong_output": "输出与测试预期不同",
              "runtime_error": "程序异常退出", "output_limit": "输出或轨迹达到限制",
              "missing_behavior": "缺少实验要求的系统调用"}
    return result(state, titles.get(state, "缺少可定位证据"), "insufficient", [],
                  ["从第一个失败用例开始。", "先核对判定条件，再检查程序状态。",
                   "查看判定中的编译或运行输出，确认最早出现的差异。"])


def output_matches(lab, output, expected):
    if lab not in {"mutex", "deadlock"}:
        return output == expected
    actual, target = output.splitlines(keepends=True), expected.splitlines(keepends=True)
    return actual[-1:] == target[-1:] and sorted(actual[:-1]) == sorted(target[:-1])


def observed_behavior(lab, case, events):
    calls = [event for event in events if event["kind"] == "syscall" and event.get("errno") is None]
    if lab == "file":
        written, rewound = set(), set()
        for event in calls:
            if not (descriptor := TEMP_FD.match(event["args"])):
                continue
            key = (event["pid"], *descriptor.groups())
            call, returned = event["call"], event["result"]
            if call == "close" and returned == "0":
                written.discard(key)
                rewound.discard(key)
            if call in {"write", "writev", "pwrite64"} and returned.isdigit() and returned != "0":
                written.add(key)
            if call == "lseek" and returned == "0" and (not case["stdin"] or key in written):
                rewound.add(key)
            if call in {"read", "readv"} and key in rewound and returned.isdigit():
                if not case["stdin"] or returned != "0":
                    return True
        return False
    if lab == "memory":
        size = str(max(1, int(case["stdin"])))
        allocations = set()
        for event in calls:
            args = event["args"].split(", ")
            if (event["call"] == "mmap" and len(args) == 6 and args[1] == size
                    and "MAP_ANONYMOUS" in args[3].split("|")
                    and {"PROT_READ", "PROT_WRITE"} <= set(args[2].split("|"))
                    and re.fullmatch(r"0x[0-9a-f]+", event["result"])):
                allocations.add((event["pid"], event["result"]))
            if (event["call"] == "munmap" and len(args) == 2 and args[1] == size
                    and event["result"] == "0" and (event["pid"], args[0]) in allocations):
                return True
        return False
    if lab in {"mutex", "deadlock"}:
        threads = worker_ids(calls)
        writers = {"A": set(), "B": set()}
        for event in calls:
            if event["call"] == "write" and event["pid"] in threads and event["result"] == "9":
                marker = re.fullmatch(r'1(?:<[^>]+>)?, "worker ([AB])\\n", 9', event["args"])
                if marker:
                    writers[marker[1]].add(event["pid"])
        return any(first != second for first in writers["A"] for second in writers["B"])
    observed = {event["call"] for event in calls}
    return all(observed.intersection(group) for group in LABS[lab]["required"])


def evaluate(lab_key, source, run_id, progress=lambda _: None):
    lab = LABS[lab_key]
    results, traces = [], []
    for case in lab["cases"]:
        progress("running")
        output = sandbox(source, case["stdin"], run_id)
        compile_log = output["compile"]
        runtime = output.get("run", {})
        case_result = {"name": case["name"], "stdin": case["stdin"], "expected": case["expected"], "compile": compile_log}
        if compile_log["code"] != 0:
            case_result["status"] = "compile_timeout" if compile_log.get("timeout") else "compile_error"
            results.append(case_result)
            traces.append([])
            break

        case_result.update(runtime)
        events = events_from(runtime["trace"])
        traces.append(events)
        case_result["status"] = (
            "trace_error" if not task_entry(events) else
            "oom" if runtime["oom"] else
            "timeout" if runtime["timeout"] else
            "output_limit" if runtime["truncated"] or runtime["trace_truncated"] else
            "runtime_error" if runtime["code"] != 0 else
            "wrong_output" if not output_matches(lab_key, runtime["stdout"], case["expected"]) else "passed"
        )
        if case_result["status"] == "passed" and not observed_behavior(lab_key, case, events):
            case_result["status"] = "missing_behavior"
        results.append(case_result)
        if case_result["status"] == "trace_error":
            break

    progress("analyzing")
    scored = results[-1]["status"] != "trace_error"
    evidence_case = next((i for i, case in enumerate(results) if case["status"] != "passed"), 0) if scored else len(results) - 1
    evidence = results[evidence_case]
    analysis = diagnose(lab_key, evidence, traces[evidence_case])
    return {
        "cases": results, "total": len(lab["cases"]), "scored": scored,
        "passed": sum(case["status"] == "passed" for case in results),
        "evidence_case": evidence_case, "diagnosis": analysis,
    }


def ai_hints(lab_key, diagnosis, events):
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return {"source": "rules", "reason": "未配置模型 API", "hints": diagnosis["hints"]}
    if diagnosis["confidence"] == "insufficient" or diagnosis["code"] in {"passed", "trace_error", "compile_timeout"}:
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
                len(refs) == len(diagnosis["evidence"]) and
                set(refs) == set(diagnosis["evidence"])):
            raise ValueError("模型提示或证据引用不符合约定")
        return {"source": "ai", "hints": hints, "evidence": refs, "model": completion["model"],
                "usage": completion.get("usage"), "duration_ms": round((monotonic() - started) * 1000)}
    except HTTPError as error:
        reason = f"模型服务返回 HTTP {error.code}"
    except OSError:
        reason = "模型服务连接失败或超时"
    except (ValueError, KeyError, IndexError, TypeError):
        reason = "模型反馈校验失败"
    return {"source": "rules", "reason": reason, "hints": diagnosis["hints"]}
