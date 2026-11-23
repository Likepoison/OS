"""Generate the tutor's Mandarin voice inside the demo environment."""
import asyncio
from array import array
from importlib.util import find_spec
from pathlib import Path
import os
import re
import sys


MODEL = Path(os.getenv("TRACETUTOR_SPEECH_MODEL",
                       Path(__file__).with_name(".tracetutor") / "voice/vits-piper-zh_CN-xiao_ya-medium"))
WEIGHTS = "zh_CN-xiao_ya-medium.onnx"
TERMS = {
    "eof": "文件结束标志", "cpu": "处理器", "pid": "进程编号", "ai": "智能辅助", "deepseek": "深度求索",
    "pipe": "创建管道", "pipe2": "创建管道", "read": "读取", "readv": "读取",
    "write": "写入", "writev": "写入", "close": "关闭", "futex": "线程同步", "mmap": "内存映射",
    "munmap": "解除内存映射", "lseek": "调整文件偏移", "openat": "打开文件", "openat2": "打开文件",
    "clone": "创建任务", "clone3": "创建任务", "wait4": "等待子进程", "waitid": "等待子进程",
    "errno": "错误编号", "io": "输入输出",
}
tts = None


def available():
    return ((MODEL / WEIGHTS).is_file() and (MODEL / "lexicon.txt").is_file()
            and find_spec("sherpa_onnx") is not None and find_spec("lameenc") is not None)


def voices():
    return (["xiaoya"] if available() else []) + (["xiaoyi"] if find_spec("edge_tts") else [])


def spoken_text(text):
    return re.sub(r"[A-Za-z][A-Za-z0-9]*", lambda word: TERMS.get(word[0].lower(), word[0]), text)


def speak_xiaoyi(text):
    import edge_tts

    async def generate():
        speech = edge_tts.Communicate(spoken_text(text), "zh-CN-XiaoyiNeural", rate="+4%", pitch="+15Hz")
        return b"".join([item["data"] async for item in speech.stream() if item["type"] == "audio"])

    audio = asyncio.run(asyncio.wait_for(generate(), timeout=8))
    if not audio:
        raise RuntimeError("Online voice returned no audio")
    return audio


def speak(text):
    import lameenc
    import sherpa_onnx

    global tts
    if tts is None:
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(MODEL / WEIGHTS),
            lexicon=str(MODEL / "lexicon.txt"),
            tokens=str(MODEL / "tokens.txt"),
        )
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=1),
            rule_fsts=",".join(str(MODEL / name) for name in ("phone.fst", "date.fst", "number.fst")),
            max_num_sentences=1,
        )
        if not config.validate():
            raise ValueError("Invalid character voice model configuration")
        tts = sherpa_onnx.OfflineTts(config)
    generated = tts.generate(spoken_text(text), sid=0, speed=1.04)
    if len(generated.samples) == 0 or generated.sample_rate <= 0:
        raise RuntimeError("Character voice returned no audio")
    samples = array("h", (int(max(-1.0, min(1.0, sample)) * 32767) for sample in generated.samples))
    if sys.byteorder != "little":
        samples.byteswap()
    encoder = lameenc.Encoder()
    encoder.set_in_sample_rate(generated.sample_rate)
    encoder.set_channels(1)
    encoder.set_bit_rate(48)
    encoder.set_quality(3)
    return bytes(encoder.encode(samples.tobytes()) + encoder.flush())
