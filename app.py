"""Local, on-demand TraceTutor demo server."""
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
import sys
from threading import BoundedSemaphore, Thread
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from engine import ai_hints, evaluate, events_from
from labs import LABS, sample
from pet_memory import StudyMemory, clean_event
import pet_speech

DATABASE = Path(os.getenv("TRACETUTOR_DB", ".tracetutor/runs.sqlite3"))
PAGE = Path(__file__).with_name("index.html")
VOICE_CACHE = PAGE.parent / ".tracetutor/voice"
if (VOICE_CACHE / "python").is_dir():
    sys.path.append(str(VOICE_CACHE / "python"))
PET_ASSETS = {
    "/pet/companion.js": "text/javascript; charset=utf-8",
    "/pet/whale-girl.png": "image/png",
    "/pet/whale-stand.webp": "image/webp",
    "/pet/whale-greeting.webp": "image/webp",
    "/pet/whale-actions.webp": "image/webp",
}
RUN_ROUTE = re.compile(r"/api/runs/([a-f0-9]{32})(?:/(events|raw)/([0-9]{1,3}))?")
MAX_SOURCE = 32_768
LIMIT = 8
WORKERS = ThreadPoolExecutor(max_workers=2)
SLOTS = BoundedSemaphore(LIMIT)
PET_MEMORY = StudyMemory()
PET_ROUTE = re.compile(r"/api/pet/sessions/([a-f0-9]{32})(?:/(close|touch))?")
VOICE_PATH = Path(os.getenv("TRACETUTOR_VOICE_MODEL", VOICE_CACHE / "vosk-model-small-cn-0.22"))
AUDIO_RATE = 16000
AUDIO_LIMIT = 12 * AUDIO_RATE * 2
VOICE_SLOT = BoundedSemaphore(1)
SPEECH_SLOT = BoundedSemaphore(1)
voice_model = None
logging.basicConfig(level=logging.INFO)


def voice_available():
    return (VOICE_PATH / "am/final.mdl").is_file() and find_spec("vosk") is not None


def transcribe_voice(audio):
    from vosk import KaldiRecognizer, Model, SetLogLevel

    global voice_model
    if voice_model is None:
        SetLogLevel(-1)
        voice_model = Model(str(VOICE_PATH))
    recognizer = KaldiRecognizer(voice_model, AUDIO_RATE)
    parts = []
    for start in range(0, len(audio), 4096):
        if recognizer.AcceptWaveform(audio[start:start + 4096]):
            parts.append(json.loads(recognizer.Result())["text"])
    parts.append(json.loads(recognizer.FinalResult())["text"])
    return re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", " ".join(parts)).strip()[:100]


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


class Handler(BaseHTTPRequestHandler):
    timeout = 15

    def send_data(self, status, payload, content_type="application/json; charset=utf-8", *, cache_control="no-store"):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=(), display-capture=()")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self' 'unsafe-inline' blob:; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; media-src blob:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/":
            return self.send_data(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if url.path in PET_ASSETS:
            cache = "private, max-age=900" if url.path.endswith(".webp") else "no-store"
            return self.send_data(200, PAGE.with_name("pet").joinpath(Path(url.path).name).read_bytes(),
                                  PET_ASSETS[url.path], cache_control=cache)
        pet = PET_ROUTE.fullmatch(url.path)
        if pet and not pet[2]:
            lab = parse_qs(url.query).get("lab", [""])[0]
            return self.pet_memory_request(pet[1], lab=lab)
        if url.path == "/api/labs":
            return self.send_data(200, {
                "ai": bool(os.getenv("DEEPSEEK_API_KEY")),
                "voice": voice_available(),
                "speech": pet_speech.available(),
                "labs": [{"id": key, "title": lab["title"], "summary": lab["summary"],
                          "sample": sample(lab), "broken": sample(lab, broken=True)}
                         for key, lab in LABS.items()],
            })
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
            return self.send_data(404, {"error": "本轮桌宠记忆已结束。"})
        except OverflowError:
            return self.send_data(429, {"error": "本轮桌宠记忆已满。请先回顾已记录内容。"})

    def pet_voice_request(self):
        if self.headers.get_content_type() != "audio/pcm":
            return self.send_data(415, {"error": "录音格式无效。"})
        try:
            size = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self.send_data(400, {"error": "录音长度无效。"})
        if size > AUDIO_LIMIT:
            return self.send_data(413, {"error": "一次最多录制 12 秒。"})
        if size < AUDIO_RATE // 2 or size % 2:
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
            try:
                transcript = transcribe_voice(audio)
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
            text = " ".join(json.loads(self.rfile.read(size))["text"].split())
            if not 0 < len(text) <= 260 or not text.isprintable():
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError, TimeoutError, RecursionError):
            return self.send_data(400, {"error": "请输入 1 至 260 个字符的朗读文本。"})
        if not pet_speech.available():
            return self.send_data(503, {"error": "鲸鱼娘的专用语音暂未就绪。"})
        if not SPEECH_SLOT.acquire(blocking=False):
            return self.send_data(429, {"error": "鲸鱼娘正在生成语音，请稍后再听。"})
        try:
            audio = pet_speech.speak(text)
        except Exception:
            logging.exception("Could not generate character voice")
            return self.send_data(503, {"error": "这次声音没有生成，请再点一次朗读。"})
        finally:
            SPEECH_SLOT.release()
        return self.send_data(200, audio, "audio/mpeg")

    def do_POST(self):
        if self.path == "/api/pet/voice":
            return self.pet_voice_request()
        if self.path == "/api/pet/speech":
            return self.pet_speech_request()
        if self.path == "/api/pet/sessions":
            if self.headers.get_content_type() != "application/json":
                return self.send_data(415, {"error": "请提交 JSON"})
            token = PET_MEMORY.create()
            if token is None:
                return self.send_data(503, {"error": "桌宠会话暂时已满。"})
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
                    return self.send_data(413, {"error": "桌宠记录超出限制。"})
                data = json.loads(self.rfile.read(size))
                event = clean_event(data)
            except (ValueError, TypeError, AttributeError, TimeoutError, RecursionError):
                return self.send_data(400, {"error": "桌宠记录格式无效。"})
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
