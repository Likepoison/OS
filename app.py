"""Local, on-demand TraceTutor demo server."""
from array import array
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from threading import BoundedSemaphore, Thread
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from engine import IMAGE, ai_hints, evaluate, events_from, sandbox
from labs import LABS, sample
from pet_memory import StudyMemory, clean_event
import pet_speech

DATABASE = Path(os.getenv("TRACETUTOR_DB", ".tracetutor/runs.sqlite3"))
PAGE = Path(__file__).with_name("index.html")
PET_POSTER = b"data:image/webp;base64," + b64encode(
    PAGE.with_name("pet").joinpath("whale-stand.webp").read_bytes()
)
VOICE_CACHE = PAGE.parent / ".tracetutor/voice"
if (VOICE_CACHE / "python").is_dir():
    sys.path.append(str(VOICE_CACHE / "python"))
PET_ASSETS = {
    "/pet/companion.js": "text/javascript; charset=utf-8",
    "/pet/whale-girl.png": "image/png",
    **{f"/pet/whale-{pose}.webp": "image/webp" for pose in (
        "stand", "greet", "walk", "listen", "talk", "sit", "snack", "play", "look", "sleep", "focus", "drag"
    )},
}
RUN_ROUTE = re.compile(r"/api/runs/([a-f0-9]{32})(?:/(events|raw)/([0-9]{1,3}))?")
MAX_SOURCE = 32_768
LIMIT = 8
WORKERS = ThreadPoolExecutor(max_workers=2)
SLOTS = BoundedSemaphore(LIMIT)
PET_MEMORY = StudyMemory()
PET_ROUTE = re.compile(r"/api/pet/sessions/([a-f0-9]{32})(?:/(close|touch))?")
VOICE_PATH = Path(os.getenv("TRACETUTOR_VOICE_MODEL",
                            VOICE_CACHE / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"))
AUDIO_RATE = 16000
AUDIO_LIMIT = 12 * AUDIO_RATE * 2
RECORDING_FORMATS = {"audio/webm": "matroska", "audio/ogg": "ogg", "audio/mp4": "mov"}
VOICE_SLOT = BoundedSemaphore(1)
SPEECH_SLOT = BoundedSemaphore(1)
CHECK_SLOT = BoundedSemaphore(1)
voice_model = None
logging.basicConfig(level=logging.INFO)


def voice_available():
    return ((VOICE_PATH / "model.int8.onnx").is_file() and (VOICE_PATH / "tokens.txt").is_file()
            and find_spec("sherpa_onnx") is not None
            and find_spec("imageio_ffmpeg") is not None)


def decode_recording(content_type, recording):
    from imageio_ffmpeg import get_ffmpeg_exe

    result = subprocess.run(
        [get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
         "-protocol_whitelist", "pipe", "-f", RECORDING_FORMATS[content_type], "-i", "pipe:0",
         "-vn", "-ac", "1", "-ar", str(AUDIO_RATE), "-t", "12", "-f", "s16le", "pipe:1"],
        input=recording, capture_output=True, check=True, timeout=8,
    )
    return result.stdout


def transcribe_voice(samples):
    from sherpa_onnx import OfflineRecognizer

    global voice_model
    if voice_model is None:
        voice_model = OfflineRecognizer.from_sense_voice(
            model=str(VOICE_PATH / "model.int8.onnx"), tokens=str(VOICE_PATH / "tokens.txt"),
            num_threads=2, language="zh", use_itn=True,
        )
    stream = voice_model.create_stream()
    # Give isolated clips room around the first and last syllables.
    waveform = [0.0] * 6400 + [sample / 32768 for sample in samples] + [0.0] * 3200
    stream.accept_waveform(AUDIO_RATE, waveform)
    voice_model.decode_stream(stream)
    return stream.result.text.strip()[:100]


@contextmanager
def database():
    conn = sqlite3.connect(DATABASE, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with database() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, lab TEXT NOT NULL, created TEXT NOT NULL,
                state TEXT NOT NULL, outcome TEXT, result TEXT
            )"""
        )
        conn.execute(
            "UPDATE runs SET state='platform_error', outcome='interrupted' "
            "WHERE state IN ('queued', 'running', 'analyzing')"
        )


def run_job(run_id, lab, source, want_ai):
    def progress(state):
        with database() as conn:
            conn.execute("UPDATE runs SET state=? WHERE id=?", (state, run_id))

    try:
        result = evaluate(lab, source, run_id, progress)
        diagnosis = result["diagnosis"]
        selected = result["cases"][result["evidence_case"]]
        if want_ai:
            result["feedback"] = ai_hints(lab, diagnosis, events_from(selected.get("trace", "")))
        else:
            result["feedback"] = {"source": "rules", "hints": diagnosis["hints"]}
        with database() as conn:
            state = "finished" if result["scored"] else "platform_error"
            conn.execute("UPDATE runs SET state=?, outcome=?, result=? WHERE id=?",
                         (state, diagnosis["code"], json.dumps(result, ensure_ascii=False), run_id))
    except Exception:
        logging.exception("Run %s failed", run_id)
        with database() as conn:
            conn.execute("UPDATE runs SET state='platform_error', outcome='platform_error' WHERE id=?", (run_id,))
    finally:
        SLOTS.release()


def demo_checks(online):
    checks = []

    def report(name, state, detail):
        checks.append({"name": name, "state": state, "detail": detail})

    try:
        with database() as conn:
            conn.execute("SELECT id FROM runs LIMIT 1").fetchone()
        report("评测服务与记录库", "ready", "页面可访问，实验记录库可读。")
    except sqlite3.Error:
        logging.exception("Demo check could not read the run database")
        report("评测服务与记录库", "error", "实验记录库读取失败。")

    evidence = None
    try:
        subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                       capture_output=True, check=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        report("Docker 服务", "error", "无法连接评测环境的 Docker 服务。")
        report("沙箱镜像", "pending", "Docker 服务可用后再检测。")
    else:
        report("Docker 服务", "ready", "Docker 已响应。")
        try:
            subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
                           capture_output=True, check=True, timeout=4)
        except (OSError, subprocess.SubprocessError):
            report("沙箱镜像", "error", "找不到评测镜像或镜像查询超时。")
        else:
            report("沙箱镜像", "ready", IMAGE)
            try:
                source = '#include <unistd.h>\nint main(void) { return write(1, "trace-ready\\n", 12) == 12 ? 0 : 1; }'
                probe = sandbox(source, "", "demo-check")
                run = probe.get("run", {})
                code_ok = probe["compile"]["code"] == 0 and run.get("code") == 0 and run.get("stdout") == "trace-ready\n"
                report("沙箱编译与运行", "ready" if code_ok else "error",
                       "固定 C 探针编译、执行和输出均通过。" if code_ok else "固定 C 探针未返回预期结果。")
                evidence = next((event for event in events_from(run.get("trace", "")) if code_ok
                                 and event.get("call") == "write" and "trace-ready" in event["text"]), None)
                report("系统调用观测", "ready" if evidence else "error",
                       f"捕获到真实 write 事件 #{evidence['id']}。" if evidence else "未捕获到可核对的探针写入事件。")
            except (OSError, RuntimeError, ValueError, KeyError):
                logging.exception("Demo sandbox probe failed")
                report("沙箱编译与运行", "error", "固定探针启动失败，请检查容器环境。")
                report("系统调用观测", "pending", "沙箱可运行后再检测。")
    if not any(check["name"] == "沙箱编译与运行" for check in checks):
        report("沙箱编译与运行", "pending", "Docker 和镜像就绪后再检测。")
        report("系统调用观测", "pending", "沙箱可运行后再检测。")

    voices = pet_speech.voices()
    recognition = voice_available()
    report("普通话转写", "configured" if recognition else "missing",
           "SenseVoice 已安装，浏览器麦克风可在助教面板实测。" if recognition else "SenseVoice 尚未安装。")
    report("小雅朗读", "configured" if "xiaoya" in voices else "missing",
           "本地模型已安装。" if "xiaoya" in voices else "本地模型尚未安装。")
    if "xiaoyi" not in voices:
        report("Xiaoyi 朗读", "missing", "在线合成依赖尚未安装。")
    elif not online:
        report("Xiaoyi 朗读", "configured", "依赖已安装，尚未验证在线响应。")
    elif not SPEECH_SLOT.acquire(blocking=False):
        report("Xiaoyi 朗读", "pending", "正在朗读，请稍后重测。")
    else:
        try:
            pet_speech.speak_xiaoyi("语音服务自检。")
            report("Xiaoyi 朗读", "ready", "在线合成返回了音频。")
        except Exception as error:
            logging.warning("Demo online voice probe failed (%s)", type(error).__name__)
            report("Xiaoyi 朗读", "error", "在线合成不可用或超时。")
        finally:
            SPEECH_SLOT.release()
    if not os.getenv("DEEPSEEK_API_KEY"):
        report("DeepSeek 提示", "missing", "未配置模型接口密钥。")
    elif not online:
        report("DeepSeek 提示", "configured", "密钥已配置，尚未验证模型响应。")
    elif not evidence:
        report("DeepSeek 提示", "pending", "需要先取得真实探针轨迹，再验证模型引用。")
    else:
        diagnosis = {"code": "probe", "title": "系统自检：使用 write 输出固定文本",
                     "confidence": "confirmed", "evidence": [evidence["id"]],
                     "hints": ["哪个调用向标准输出写入数据？", "调用的返回值说明了什么？", "可以用哪条轨迹核对写入？"]}
        reply = ai_hints("pipe", diagnosis, [evidence])
        if reply["source"] == "ai":
            report("DeepSeek 提示", "ready", "模型返回分层提示，且引用了真实探针证据。")
        else:
            report("DeepSeek 提示", "error", reply["reason"])
    return {"checks": checks}


class Handler(BaseHTTPRequestHandler):
    timeout = 15

    def send_data(self, status, payload, content_type="application/json; charset=utf-8", *, cache_control="no-store", headers=()):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=(), display-capture=()")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; media-src blob:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/":
            page = PAGE.read_bytes().replace(b'src="/pet/whale-stand.webp"', b'src="' + PET_POSTER + b'"', 1)
            return self.send_data(200, page, "text/html; charset=utf-8")
        if url.path in PET_ASSETS:
            cache = "private, max-age=900" if url.path.endswith(".webp") else "no-store"
            return self.send_data(200, PAGE.with_name("pet").joinpath(Path(url.path).name).read_bytes(),
                                  PET_ASSETS[url.path], cache_control=cache)
        pet = PET_ROUTE.fullmatch(url.path)
        if pet and not pet[2]:
            lab = parse_qs(url.query).get("lab", [""])[0]
            return self.pet_memory_request(pet[1], lab=lab)
        if url.path == "/api/labs":
            voices = pet_speech.voices()
            return self.send_data(200, {
                "ai": bool(os.getenv("DEEPSEEK_API_KEY")),
                "voice": voice_available(),
                "speech": bool(voices),
                "speech_voices": voices,
                "labs": [{"id": key, "title": lab["title"], "summary": lab["summary"],
                          "starter": lab["starter"]}
                         for key, lab in LABS.items()],
            })
        if url.path == "/api/labs/sample":
            lab = LABS.get(parse_qs(url.query).get("lab", [""])[0])
            if lab is None:
                return self.send_data(404, {"error": "找不到该实验的正确样例。"})
            return self.send_data(200, {"source": sample(lab)})
        if url.path == "/api/runs":
            lab = parse_qs(url.query).get("lab", [""])[0]
            with database() as conn:
                records = conn.execute(
                    "SELECT id, lab, created, state, outcome FROM runs WHERE (?='' OR lab=?) "
                    "ORDER BY created DESC LIMIT 50", (lab, lab),
                )
                counts = conn.execute(
                    "SELECT outcome, count(*) AS count FROM runs "
                    "WHERE outcome IS NOT NULL AND (?='' OR lab=?) GROUP BY outcome ORDER BY count DESC",
                    (lab, lab),
                )
                return self.send_data(200, {"runs": [dict(row) for row in records],
                                            "counts": [dict(row) for row in counts]})

        match = RUN_ROUTE.fullmatch(url.path)
        if not match:
            return self.send_data(404, {"error": "地址不存在"})
        run_id, action, index = match.groups()
        with database() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return self.send_data(404, {"error": "找不到这条实验记录"})
        record = dict(row)
        result = json.loads(record.pop("result") or "null")
        if action:
            index = int(index)
            if not result or index >= len(result["cases"]):
                return self.send_data(404, {"error": "找不到该用例的轨迹"})
            raw = result["cases"][index].get("trace", "")
            if action == "raw":
                return self.send_data(200, raw.encode(), "text/plain; charset=utf-8")
            events = events_from(raw)
            query = parse_qs(url.query)
            if query.get("only") == ["evidence"]:
                ids = result["diagnosis"]["evidence"] if index == result["evidence_case"] else []
                events = [event for event in events if event["id"] in ids]
            elif query.get("q", [""])[0]:
                term = query["q"][0][:100].casefold()
                events = [event for event in events
                          if term in event["text"].casefold() or term == str(event["pid"])]
            try:
                requested = query.get("page", ["0"])[0]
                last = max(0, (len(events) - 1) // 40)
                page = last if requested == "last" else min(last, max(0, int(requested)))
            except ValueError:
                return self.send_data(400, {"error": "页码无效"})
            return self.send_data(200, {"events": events[page * 40:(page + 1) * 40],
                                        "page": page, "total": len(events)})
        if result:
            for case in result["cases"]:
                case["trace_available"] = bool(case.pop("trace", None))
                for group in (case, case["compile"]):
                    for stream in ("stdout", "stderr"):
                        if stream in group and len(group[stream]) > 8192:
                            group[stream] = group[stream][:8192] + "\n[页面显示已截取]"
        return self.send_data(200, {**record, "result": result})

    def pet_memory_request(self, token, **kwargs):
        try:
            return self.send_data(200, PET_MEMORY.request(token, **kwargs))
        except KeyError:
            return self.send_data(404, {"error": "本轮小助教记忆已结束。"})
        except OverflowError:
            return self.send_data(429, {"error": "本轮小助教记忆已满。请先回顾已记录内容。"})

    def pet_voice_request(self):
        content_type = self.headers.get_content_type()
        raw = content_type == "audio/pcm"
        if not raw and content_type not in RECORDING_FORMATS:
            return self.send_data(415, {"error": "录音格式无效。"})
        try:
            size = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self.send_data(400, {"error": "录音长度无效。"})
        if size > (AUDIO_LIMIT if raw else 128 * 1024):
            return self.send_data(413, {"error": "一次最多录制 12 秒。"})
        if size < (AUDIO_RATE // 2 if raw else 100) or (raw and size % 2):
            return self.send_data(400, {"error": "录音太短，请说完后再结束。"})
        if not voice_available():
            return self.send_data(503, {"error": "演示环境的普通话识别暂不可用。"})
        if not VOICE_SLOT.acquire(blocking=False):
            return self.send_data(429, {"error": "语音转写正在处理，请稍后重试。"})
        try:
            try:
                audio = self.rfile.read(size)
            except TimeoutError:
                return self.send_data(408, {"error": "录音上传超时，请重试。"})
            if len(audio) != size:
                return self.send_data(400, {"error": "录音未传完，请重试。"})
            if not raw:
                try:
                    audio = decode_recording(content_type, audio)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    return self.send_data(400, {"error": "录音无法解码，请再试一次。"})
                except (OSError, RuntimeError):
                    logging.exception("Voice decoder unavailable")
                    return self.send_data(503, {"error": "录音解码服务暂不可用。"})
                if len(audio) < AUDIO_RATE // 2:
                    return self.send_data(400, {"error": "录音太短，请说完后再结束。"})
            samples = array("h", audio)
            if sys.byteorder != "little":
                samples.byteswap()
            if not any(abs(sample) >= 64 for sample in samples):
                return self.send_data(200, {"text": "", "reason": "no_signal"})
            try:
                transcript = transcribe_voice(samples)
            except Exception:
                logging.exception("Voice recognition failed")
                return self.send_data(503, {"error": "普通话识别暂时失败，请重试或使用文字。"})
            return self.send_data(200, {"text": transcript})
        finally:
            VOICE_SLOT.release()

    def pet_speech_request(self):
        if self.headers.get_content_type() != "application/json":
            return self.send_data(415, {"error": "请提交 JSON 格式的朗读文本。"})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 4096:
                return self.send_data(413, {"error": "朗读文本超出长度限制。"})
            request = json.loads(self.rfile.read(size))
            text = " ".join(request["text"].split())
            if not 0 < len(text) <= 260 or not text.isprintable():
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError, TimeoutError, RecursionError):
            return self.send_data(400, {"error": "请输入 1 至 260 个字符的朗读文本。"})
        voices = pet_speech.voices()
        voice = request.get("voice", voices[0] if voices else "xiaoyi")
        if voice not in ("xiaoya", "xiaoyi"):
            return self.send_data(400, {"error": "请选择小雅或 Xiaoyi 音色。"})
        if voice not in voices:
            return self.send_data(503, {"error": "助教的专用语音暂未就绪。"})
        if not SPEECH_SLOT.acquire(blocking=False):
            return self.send_data(429, {"error": "助教正在生成语音，请稍后再听。"})
        try:
            if voice == "xiaoyi":
                try:
                    audio = pet_speech.speak_xiaoyi(text)
                except Exception as error:
                    logging.warning("Online tutor voice unavailable (%s)", type(error).__name__)
                    if "xiaoya" not in voices:
                        return self.send_data(503, {"error": "在线语音暂不可用，请稍后重试。"})
                    voice = "xiaoya"
            if voice == "xiaoya":
                audio = pet_speech.speak(text)
        except Exception:
            logging.exception("Could not generate character voice")
            return self.send_data(503, {"error": "这次声音没有生成，请再点一次朗读。"})
        finally:
            SPEECH_SLOT.release()
        return self.send_data(200, audio, "audio/mpeg", headers=(("X-TraceTutor-Voice", voice),))

    def do_POST(self):
        if self.path == "/api/demo-check":
            if self.headers.get_content_type() != "application/json":
                return self.send_data(415, {"error": "请提交 JSON 格式的检查选项。"})
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 256:
                    return self.send_data(413, {"error": "检查请求过长。"})
                online = json.loads(self.rfile.read(size)).get("online", False)
                if type(online) is not bool:
                    raise ValueError
            except (ValueError, AttributeError, TimeoutError, RecursionError):
                return self.send_data(400, {"error": "检查选项格式无效。"})
            if not CHECK_SLOT.acquire(blocking=False):
                return self.send_data(429, {"error": "系统自检正在运行，请稍后重试。"})
            try:
                return self.send_data(200, demo_checks(online))
            finally:
                CHECK_SLOT.release()
        if self.path == "/api/pet/voice":
            return self.pet_voice_request()
        if self.path == "/api/pet/speech":
            return self.pet_speech_request()
        if self.path == "/api/pet/sessions":
            if self.headers.get_content_type() != "application/json":
                return self.send_data(415, {"error": "请提交 JSON"})
            token = PET_MEMORY.create()
            if token is None:
                return self.send_data(503, {"error": "小助教会话暂时已满。"})
            return self.send_data(HTTPStatus.CREATED, {"id": token})
        if pet := PET_ROUTE.fullmatch(self.path):
            if pet[2] == "close":
                PET_MEMORY.close(pet[1])
                return self.send_data(200, {"ok": True})
            if self.headers.get_content_type() != "application/json":
                return self.send_data(415, {"error": "请提交 JSON"})
            if pet[2] == "touch":
                return self.pet_memory_request(pet[1])
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 4096:
                    return self.send_data(413, {"error": "小助教记录超出限制。"})
                data = json.loads(self.rfile.read(size))
                event = clean_event(data)
            except (ValueError, TypeError, AttributeError, TimeoutError, RecursionError):
                return self.send_data(400, {"error": "小助教记录格式无效。"})
            return self.pet_memory_request(pet[1], event=event)
        if self.path != "/api/runs":
            return self.send_data(404, {"error": "地址不存在"})
        if self.headers.get_content_type() != "application/json":
            return self.send_data(415, {"error": "请提交 JSON"})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= MAX_SOURCE * 6 + 1024:
                return self.send_data(413, {"error": "请求大小超出限制"})
            data = json.loads(self.rfile.read(size))
            lab, source = data["lab"], data["source"]
            if not isinstance(lab, str) or lab not in LABS or not isinstance(source, str):
                raise ValueError
            if not source.strip() or len(source.encode()) > MAX_SOURCE or "\x00" in source:
                raise ValueError
        except (ValueError, KeyError, TypeError, TimeoutError, RecursionError):
            return self.send_data(400, {"error": "请选择有效实验，提交 1–32 KiB 的 C 源代码"})
        if not SLOTS.acquire(blocking=False):
            return self.send_data(429, {"error": "运行队列已满，请稍后重试"})
        run_id = uuid4().hex
        try:
            with database() as conn:
                conn.execute("INSERT INTO runs (id,lab,created,state) VALUES (?,?,?,'queued')",
                             (run_id, lab, datetime.now(timezone.utc).isoformat()))
            try:
                WORKERS.submit(run_job, run_id, lab, source, data.get("ai") is True)
            except RuntimeError:
                with database() as conn:
                    conn.execute("UPDATE runs SET state='platform_error', outcome='platform_error' WHERE id=?", (run_id,))
                raise
        except (RuntimeError, sqlite3.Error):
            SLOTS.release()
            logging.exception("Could not enqueue run %s", run_id)
            return self.send_data(503, {"error": "评测服务暂时无法提交任务，请稍后重试。"})
        return self.send_data(HTTPStatus.ACCEPTED, {"id": run_id})


if __name__ == "__main__":
    initialize()
    Thread(target=PET_MEMORY.reap, daemon=True).start()
    with ThreadingHTTPServer(("127.0.0.1", 8000), Handler) as server:
        print("TraceTutor · http://127.0.0.1:8000", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
