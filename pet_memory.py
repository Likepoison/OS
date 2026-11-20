"""Transient, per-page study history. The evaluation database is independent."""
from threading import Lock
from time import monotonic, sleep
from uuid import uuid4

from labs import LABS

IDLE_SECONDS = 600
MAX_SESSIONS = 32
MAX_EVENTS = 4000


def run_id(value):
    if isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value):
        return value
    return None


def clean_event(data):
    kind = data.get("type")
    if kind == "view" and data.get("view") in ("grade", "trace", "hints", "history"):
        total = data.get("total")
        return {"type": kind, "view": data["view"], "total": total if type(total) is int and total >= 0 else None,
                "run_id": run_id(data.get("run_id"))}
    if kind == "event":
        number, call = data.get("id"), data.get("call")
        if (type(number) is int and number > 0 and isinstance(call, str)
                and call.isascii() and call.replace("_", "").isalnum() and len(call) <= 40):
            errno = data.get("errno")
            return {"type": kind, "id": number, "call": call, "kind": data.get("kind") if data.get("kind") in ("syscall", "partial", "pending") else None,
                    "errno": errno if isinstance(errno, str) and errno.isascii()
                    and errno.isalnum() and len(errno) <= 20 else None}
    if kind == "question":
        question, reply = data.get("question"), data.get("reply")
        if isinstance(question, str) and 0 < len(question) <= 100 and isinstance(reply, str) and len(reply) <= 800:
            return {"type": kind, "question": question, "reply": reply, "recap": data.get("recap") is True}
    lab = data.get("lab")
    if isinstance(lab, str) and lab in LABS:
        if kind == "answer" and type(data.get("correct")) is bool and type(data.get("choice")) is int and 0 <= data["choice"] <= 2:
            return {"type": kind, "lab": lab, "choice": data["choice"], "correct": data["correct"]}
        if kind == "run":
            score = data.get("score")
            if (isinstance(score, list) and len(score) == 2 and all(type(n) is int for n in score)
                    and 0 <= score[0] <= score[1] <= 100):
                return {"type": kind, "lab": lab, "score": score, "run_id": run_id(data.get("run_id"))}
    raise ValueError("invalid study event")


class StudyMemory:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.sessions = {}

    def expire(self):
        now = self.clock()
        with self.lock:
            for key, (deadline, _) in list(self.sessions.items()):
                if deadline <= now:
                    del self.sessions[key]

    def reap(self):
        while True:
            sleep(60)
            self.expire()

    def create(self):
        self.expire()
        with self.lock:
            if len(self.sessions) >= MAX_SESSIONS:
                return None
            token = uuid4().hex
            self.sessions[token] = (self.clock() + IDLE_SECONDS, [])
            return token

    def close(self, token):
        with self.lock:
            self.sessions.pop(token, None)

    def request(self, token, *, event=None, lab=None):
        now = self.clock()
        with self.lock:
            session = self.sessions.get(token)
            if session is None:
                raise KeyError(token)
            deadline, events = session
            if deadline <= now:
                del self.sessions[token]
                raise KeyError(token)
            self.sessions[token] = (now + IDLE_SECONDS, events)
            if event is not None:
                if len(events) >= MAX_EVENTS:
                    raise OverflowError("study session full")
                events.append(event)
            if lab is None:
                return {"ok": True}
            copy = list(events)

        runs = [e for e in copy if e["type"] == "run"]
        answers = [e for e in copy if e["type"] == "answer"]
        questions = [e for e in copy if e["type"] == "question"]
        lab_runs = [e for e in runs if e["lab"] == lab]
        lab_answers = [e for e in answers if e["lab"] == lab]
        return {
            "views": len({e["view"] for e in copy if e["type"] == "view"}),
            "runs": len(runs),
            "answers": len(answers),
            "questions": len(questions),
            "previous_reply": next((e["reply"] for e in reversed(questions) if not e["recap"]), ""),
            "last_event": next((e for e in reversed(copy) if e["type"] == "event"), None),
            "study": {
                "runs": len(lab_runs),
                "answers": len(lab_answers),
                "correct": sum(e["correct"] for e in lab_answers),
                "score": lab_runs[-1]["score"] if lab_runs else None,
            },
        }
