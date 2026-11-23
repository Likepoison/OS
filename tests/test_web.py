import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest import TestCase
from urllib.error import URLError
from urllib.request import urlopen


class Demo(TestCase):
    def test_browser_flow(self):
        from playwright.sync_api import expect, sync_playwright

        with TemporaryDirectory() as temp:
            env = {**os.environ, "TRACETUTOR_DB": str(Path(temp) / "test.sqlite3")}
            live = env.get("TRACE_LIVE_AI") == "1"
            if live:
                self.assertTrue(env.get("DEEPSEEK_API_KEY"), "GitHub Actions model secret is missing")
            else:
                env.pop("DEEPSEEK_API_KEY", None)
            server = subprocess.Popen([sys.executable, "app.py"], env=env)
            try:
                deadline = monotonic() + 10
                while True:
                    try:
                        with urlopen("http://127.0.0.1:8000/api/labs", timeout=1) as rs:
                            self.assertEqual(len(json.load(rs)["labs"]), 6)
                        break
                    except URLError:
                        if monotonic() >= deadline or server.poll() is not None:
                            raise
                        sleep(.2)

                with sync_playwright() as runtime:
                    browser = runtime.chromium.launch(args=[
                        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                    ])
                    context = browser.new_context(viewport={"width": 1440, "height": 960})
                    page = context.new_page()
                    session_ids = []
                    page.add_init_script("""
                        window.SpeechRecognition = class {
                          start() { window.currentDictation = this; }
                          stop() {}
                          abort() { this.cancelled = true; }
                        };
                        window.Audio = class {
                          constructor(url) { this.url = url; this.duration = 6; this.currentTime = 0; }
                          play() { window.currentNarration = this; this.paused = false; this.onplaying?.(); return Promise.resolve(); }
                          pause() { this.paused = true; }
                        };
                    """)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def capture_session(response):
                        if response.url.endswith("/api/pet/sessions") and response.status == 201:
                            session_ids.append(response.json()["id"])

                    page.on("response", capture_session)
                    page.route("**/api/labs", lambda route: route.fulfill(
                        status=200, content_type="text/html", body="<p>Sign in to continue</p>"))
                    page.goto("http://127.0.0.1:8000")
                    expect(page.get_by_role("alert")).to_contain_text("从 Ports 重新打开私有预览")
                    expect(page.get_by_role("button", name="运行实验")).to_be_disabled()
                    page.unroute("**/api/labs")

                    def spoken_configuration(route):
                        config = route.fetch().json()
                        config.update(voice=False, speech=True, speech_voices=["xiaoyi", "xiaoya"])
                        route.fulfill(json=config)

                    later_speech = []
                    defer_replay = False

                    def synthesize(route):
                        if not defer_replay and route.request.post_data_json["voice"] == "xiaoyi":
                            route.fulfill(content_type="audio/mpeg", body=b"\xff\xfb",
                                          headers={"X-TraceTutor-Voice": "xiaoya"})
                        else:
                            later_speech.append(route)

                    page.route("**/api/labs", spoken_configuration)
                    page.route("**/api/pet/speech", synthesize)
                    page.reload()
                    expect(page).to_have_title("TraceTutor——操作系统实验评测与智能诊断平台")
                    expect(page.locator(".brand")).to_contain_text("TraceTutor")
                    run = page.get_by_role("button", name="运行实验")
                    expect(run).to_be_enabled()
                    source = page.locator("#source")
                    source.fill("first line")
                    source.press("End")
                    source.press("Enter")
                    expect(source).to_have_value("first line\n")
                    expect(page.locator("#status")).to_have_text("待提交")
                    page.locator("#bad").click()
                    self.assertEqual(page.locator(".grid > .panel").evaluate_all(
                        "(nodes) => new Set(nodes.map(n => n.getBoundingClientRect().bottom)).size"), 1)
                    quote = page.locator("#quote")
                    quote_source = page.locator("#quote-source")
                    self.assertTrue(quote_source.get_attribute("href").startswith("https://"))
                    expect(quote.locator(".quote-line")).to_have_css("white-space", "nowrap")
                    self.assertGreater(quote_source.bounding_box()["y"], page.locator("#quote-text").bounding_box()["y"])
                    self.assertTrue(quote.evaluate("(node) => node.scrollWidth <= node.clientWidth"))
                    self.assertEqual(page.evaluate("""
                        Math.min(...[...document.querySelectorAll(
                          'h1,h2,h3,p,span,button,select,textarea,input,small,legend,code,pre,a'
                        )].filter(el => el.getClientRects().length && (
                          el.textContent.trim() || el.matches('input,textarea,select')
                        )).map(el => parseFloat(getComputedStyle(el).fontSize)))
                    """), 18)
                    page.get_by_role("button", name="外观设置").click()
                    appearance = page.get_by_role("dialog", name="外观设置")
                    appearance.get_by_label("界面主题").select_option("sage")
                    appearance.get_by_label("背景图案").select_option("waves")
                    expect(page.locator("html")).to_have_attribute("data-theme", "sage")
                    expect(page.locator("body")).to_have_attribute("data-backdrop", "waves")
                    appearance.get_by_label("自定义背景图片").set_input_files({
                        "name": "invalid.png", "mimeType": "image/png", "buffer": b"invalid",
                    })
                    expect(appearance.locator("#background-note")).to_contain_text("图片无法打开")
                    appearance.get_by_label("自定义背景图片").set_input_files("pet/whale-girl.png")
                    expect(page.locator("body")).to_have_attribute("data-backdrop", "custom")
                    appearance.get_by_label("背景图案").select_option("grid")
                    appearance.get_by_label("界面主题").select_option("blue")
                    appearance.get_by_role("button", name="完成").click()
                    code = page.get_by_role("textbox", name="C 源代码")
                    original_code = code.input_value()
                    page.get_by_role("button", name="代码样式").click()
                    options = page.get_by_role("dialog", name="代码样式")
                    options.get_by_label("字号").select_option("22")
                    options.get_by_label("制表符宽度").select_option("2")
                    options.get_by_label("自动换行").check()
                    expect(code).to_have_css("font-size", "22px")
                    expect(code).to_have_css("tab-size", "2")
                    expect(code).to_have_attribute("wrap", "soft")
                    expect(code).to_have_value(original_code)
                    options.get_by_label("自动换行").uncheck()
                    options.get_by_role("button", name="完成").click()
                    pet = page.get_by_role("button", name="小助教", exact=True)
                    pet_panel = page.get_by_role("complementary", name="小助教", exact=True)
                    pet_reply = pet_panel.locator("#pet-reply")
                    portrait = pet.locator(".pet-figure")
                    poster = portrait.locator(".pet-stand")
                    expect(poster).to_have_attribute("src", re.compile(r"^data:image/webp;base64,"))
                    self.assertEqual(poster.evaluate("""async image => {
                      await image.decode();
                      return [image.naturalWidth, image.naturalHeight];
                    }"""), [336, 336])
                    pet_bubble = page.locator("#pet-bubble")
                    self.assertGreater(portrait.bounding_box()["width"], 100)
                    expect(pet).to_have_css("background-color", "rgba(0, 0, 0, 0)")
                    page.emulate_media(reduced_motion="no-preference")
                    pet.hover()
                    expect(pet).to_have_attribute("data-pose", "greet")
                    page.mouse.move(20, 130)
                    pet.hover(position={"x": 8, "y": 55})
                    expect(pet).to_have_attribute("data-pose", "look")
                    expect(pet).to_have_attribute("data-gaze", "pointer")
                    first_gaze = pet.evaluate("(node) => node.style.getPropertyValue('--gaze-frame')")
                    pet.hover(position={"x": int(pet.bounding_box()["width"]) - 8, "y": 55})
                    self.assertNotEqual(first_gaze, pet.evaluate("(node) => node.style.getPropertyValue('--gaze-frame')"))
                    page.mouse.move(20, 130)
                    pet.hover()
                    expect(pet).to_have_attribute("data-pose", "play")
                    original = pet.bounding_box()
                    page.mouse.down()
                    page.mouse.move(original["x"] - 70, original["y"] - 60, steps=5)
                    page.mouse.up()
                    self.assertLess(pet.bounding_box()["x"], original["x"] - 50)
                    expect(pet_panel).to_be_hidden()
                    pet.focus()
                    x = pet.bounding_box()["x"]
                    page.keyboard.press("ArrowLeft")
                    self.assertLess(pet.bounding_box()["x"], x)
                    page.keyboard.press("Enter")
                    expect(pet_panel).to_be_visible()
                    pet_panel.get_by_role("button", name="来道小测").click()
                    pet_panel.get_by_role("button", name="任意一个写端被关闭后").click()
                    expect(pet_reply).to_contain_text("再想一步")
                    pet_panel.get_by_role("button", name="最后一个写端被关闭后").click()
                    expect(pet_reply).to_contain_text("答对啦")
                    voice = pet_panel.get_by_role("button", name="语音输入")
                    prompt = pet_panel.get_by_role("textbox", name="问助教")
                    auto_read = pet_panel.get_by_label("自动朗读")
                    expect(auto_read).to_be_checked()
                    auto_read.uncheck()
                    pet_panel.locator("#pet-title").focus()
                    page.keyboard.down("t")
                    expect(pet_panel.get_by_role("button", name="停止聆听")).to_be_visible()
                    page.evaluate("""() => {
                      window.currentDictation.onresult({resultIndex: 0, results: [[{transcript: "你好"}]]});
                      window.currentDictation.onend();
                    }""")
                    expect(pet_panel.locator("#pet-heard")).to_be_hidden()
                    page.keyboard.up("t")
                    expect(pet_panel.locator("#pet-heard")).to_have_text("听到「你好」，已发送。")
                    expect(pet_reply).to_contain_text("你好呀")
                    auto_read.check()
                    prompt.fill("尚未发送的草稿")
                    prompt.dispatch_event("keydown", {"key": "Enter", "code": "Enter", "isComposing": True})
                    expect(prompt).to_have_value("尚未发送的草稿")
                    voice.click()
                    expect(pet_panel.get_by_role("button", name="停止聆听")).to_be_visible()
                    expect(pet_panel.get_by_label("朗读音色")).to_have_count(0)
                    with page.expect_request("**/api/pet/speech") as spoken, page.expect_request(
                            lambda request: request.url.endswith("/api/pet/speech")
                            and request.post_data_json["voice"] == "xiaoya") as prefetched:
                        page.evaluate("""window.currentDictation.onresult({
                            resultIndex: 0, results: [[{transcript: "我的学习进度怎样"}]]
                        })""")
                    expect(prompt).to_have_value("尚未发送的草稿")
                    expect(pet_reply).to_contain_text("概念题答对 1/2 次")
                    self.assertEqual(spoken.value.post_data_json["voice"], "xiaoyi")
                    self.assertTrue(spoken.value.post_data_json["text"].startswith("当前实验评测"))
                    self.assertIn("概念题答对 1/2 次", prefetched.value.post_data_json["text"])
                    expect(pet).to_have_attribute("data-pose", "talk")
                    expect(pet_panel.locator("#pet-voice-status")).to_be_hidden()
                    text = spoken.value.post_data_json["text"]
                    expect(pet_bubble).to_have_attribute("data-kind", "spoken")
                    expect(pet_bubble).to_have_text(text[:1])
                    cue = pet_bubble.bounding_box()
                    self.assertLess(cue["y"] + cue["height"], pet.bounding_box()["y"])
                    page.evaluate("() => { window.currentNarration.currentTime = 3; }")
                    expect(pet_bubble).to_have_text(text[:1 + len(text) // 2])
                    page.evaluate("() => window.currentNarration.onended()")
                    expect(pet_bubble).to_have_text(text)
                    expect(pet).to_have_attribute("data-pose", "focus")
                    remaining = re.findall(r"[^。！？!?]+[。！？!?]*|[。！？!?]+", pet_reply.inner_text())[1:]
                    for index, sentence in enumerate(remaining):
                        later_speech[index].fulfill(content_type="audio/mpeg", body=b"\xff\xfb")
                        expect(pet_bubble).to_have_text(text + sentence[:1])
                        page.evaluate("() => window.currentNarration.onended()")
                        text += sentence
                        expect(pet_bubble).to_have_text(text)
                    expect(pet_panel.get_by_role("button", name="朗读回复")).to_be_enabled()
                    defer_replay = True
                    with page.expect_request("**/api/pet/speech") as replay:
                        pet_panel.get_by_role("button", name="朗读回复").click()
                    self.assertEqual(replay.value.post_data_json["voice"], "xiaoyi")
                    expect(pet_bubble).to_be_hidden()
                    pet_panel.get_by_role("button", name="停止朗读").click()
                    pet_panel.get_by_label("自动朗读").uncheck()
                    voice.click()
                    page.evaluate("window.currentDictation.onerror({error:'not-allowed'})")
                    expect(pet_panel.locator("#pet-voice-status")).to_contain_text("可以继续打字")
                    voice.click()
                    page.evaluate("""window.currentDictation.onresult({
                        resultIndex: 0, results: [[{transcript: "啊那个"}]]
                    })""")
                    expect(pet_reply).to_contain_text("还没对上当前实验")
                    user_text = "<b>无关内容</b>"
                    requests = []
                    def collect(request):
                        requests.append(request)

                    page.on("request", collect)
                    pet_panel.get_by_role("textbox", name="问助教").fill(user_text)
                    pet_panel.get_by_role("textbox", name="问助教").press("Enter")
                    expect(pet_reply).to_contain_text("我可以陪你看本次结果")
                    self.assertNotIn(user_text, pet_panel.inner_text())
                    self.assertTrue(all("/api/pet/sessions" in req.url or
                                        (req.method == "GET" and "/pet/" in req.url) for req in requests))
                    self.assertEqual(page.evaluate("localStorage.length + sessionStorage.length"), 0)
                    page.remove_listener("request", collect)
                    pet_panel.get_by_role("button", name="回到角落").click()
                    self.assertEqual(pet.bounding_box()["x"], original["x"])
                    voice.click()
                    pet_panel.get_by_role("button", name="隐藏助教").click()
                    self.assertTrue(page.evaluate("window.currentDictation.cancelled"))
                    expect(pet).to_be_hidden()
                    expect(pet_bubble).to_be_hidden()
                    expect(pet_panel).to_be_hidden()
                    page.get_by_role("button", name="显示助教").click()
                    expect(pet).to_be_visible()
                    expect(pet_bubble).to_be_visible()
                    pet.click()
                    page.keyboard.press("Escape")
                    expect(pet_panel).to_be_hidden()
                    expect(pet).to_be_focused()
                    mobile = context.new_page()
                    try:
                        mobile.set_viewport_size({"width": 390, "height": 844})
                        mobile.clock.install()
                        mobile.add_init_script("""
                            let hiddenTab = true;
                            Object.defineProperty(document, "hidden", {get: () => hiddenTab});
                            window.showTraceTab = () => {
                              hiddenTab = false;
                              document.dispatchEvent(new Event("visibilitychange"));
                            };
                        """)
                        pending_script = []
                        pending_art = []
                        mobile.route("**/pet/companion.js", lambda route: pending_script.append(route))
                        mobile.route("**/pet/whale-greet.webp", lambda route: pending_art.append(route))
                        with mobile.expect_request("**/pet/companion.js"):
                            mobile.goto("http://127.0.0.1:8000", wait_until="commit")
                        expect(mobile.get_by_role("button", name="语音提问")).to_be_disabled()
                        expect(mobile.locator("#pet-bubble")).to_contain_text("我是小助教")
                        pending_script[0].continue_()
                        expect(mobile.get_by_role("button", name="问助教")).to_be_enabled()
                        mobile_pet = mobile.locator("#pet-launch")
                        mobile_poster = mobile_pet.locator(".pet-stand")
                        expect(mobile_poster).to_be_visible()
                        with mobile.expect_request("**/pet/whale-greet.webp"):
                            mobile.evaluate("window.showTraceTab()")
                        expect(mobile.locator("#pet-bubble")).to_have_attribute("data-kind", "welcome")
                        expect(mobile_pet).to_have_attribute("data-pose", "greet")
                        expect(mobile_pet.locator(".pet-figure")).to_have_css("animation-name", "pet-hello")
                        self.assertTrue(pending_art)
                        pending_art[0].continue_()
                        expect(mobile_pet).to_have_attribute("data-art", "greet")
                        self.assertEqual(mobile_pet.locator(".pet-strip").evaluate("(image) => image.naturalWidth"), 2048)
                        expect(mobile_poster).to_be_hidden()
                        expect(mobile.locator("#pet-bubble")).to_contain_text("我是小助教")
                        self.assertEqual(mobile.evaluate("document.documentElement.scrollWidth"), 390)
                        expect(mobile.locator(".quote-line")).to_have_css("white-space", "nowrap")
                        self.assertTrue(mobile.locator(".grid > .panel").evaluate_all(
                            "(nodes) => nodes[1].getBoundingClientRect().top > nodes[0].getBoundingClientRect().bottom"))
                        mobile.mouse.move(20, 120)
                        home = mobile_pet.bounding_box()["x"]
                        mobile.route("**/pet/whale-walk.webp", lambda route: route.fulfill(
                            content_type="image/webp", body=b"invalid sprite"))
                        with mobile.expect_response("**/pet/whale-walk.webp"):
                            mobile.clock.run_for(5700)
                        expect(mobile_pet).to_have_attribute("data-roaming", "true")
                        expect(mobile_poster).to_be_visible()
                        expect(mobile_pet.locator(".pet-strip")).to_have_count(0)
                        self.assertLess(float(mobile_pet.evaluate("(el) => parseFloat(el.style.left)")), home - 40)
                        mobile.clock.run_for(5200)
                        expect(mobile_pet).to_have_attribute("data-pose", "look")
                        mobile.clock.run_for(5200)
                        expect(mobile_pet).to_have_attribute("data-pose", "sit")
                        mobile.clock.run_for(5200)
                        expect(mobile_pet).to_have_attribute("data-pose", "snack")
                        mobile.clock.run_for(5200)
                        expect(mobile_pet).to_have_attribute("data-pose", "play")
                        mobile.clock.run_for(5200)
                        expect(mobile_pet).to_have_attribute("data-pose", "sleep")
                        mobile.get_by_role("button", name="外观设置").click()
                        mobile.get_by_label("小助教自由活动").uncheck()
                        mobile.get_by_label("小助教主动气泡").uncheck()
                        mobile.get_by_role("button", name="完成").click()
                        mobile.clock.fast_forward(65000)
                        expect(mobile_pet).to_have_attribute("data-motion", "false")
                        expect(mobile.locator("#pet-bubble")).to_be_hidden()
                    finally:
                        mobile.close()
                    cloud_voice = context.new_page()
                    try:
                        pending_config = []
                        session_requests = []
                        voice_responses = iter([{"text": "我的学习进驻怎样"}, {"text": "", "reason": "no_signal"}])
                        cloud_voice.add_init_script("""(() => {
                          const media = navigator.mediaDevices;
                          const capture = media.getUserMedia.bind(media);
                          const enumerate = media.enumerateDevices.bind(media);
                          media.enumerateDevices = async () => (await enumerate()).filter(device =>
                            device.deviceId !== window.removedMicrophone);
                          media.getUserMedia = async settings => {
                            window.lastCapture = settings.audio;
                            if (window.denyMicrophone) throw new DOMException("Blocked", "NotAllowedError");
                            const stream = await capture(settings);
                            window.lastInputTrack = stream.getAudioTracks()[0];
                            return stream;
                          };
                        })();""")

                        def capture_session_request(request):
                            if "/api/pet/sessions" in request.url:
                                session_requests.append(request)

                        cloud_voice.on("request", capture_session_request)

                        def check_recording(route):
                            self.assertTrue(route.request.headers["content-type"].startswith("audio/webm"))
                            clip = route.request.post_data_buffer
                            self.assertTrue(clip.startswith(b"\x1a\x45\xdf\xa3"))
                            self.assertLess(len(clip), 16000)
                            route.fulfill(json=next(voice_responses))

                        cloud_voice.route("**/api/labs", lambda route: pending_config.append(route))
                        cloud_voice.route("**/api/pet/voice", check_recording)
                        cloud_voice.route("**/api/pet/speech", lambda route: route.fulfill(
                            status=503, json={"error": "朗读测试服务暂不可用。"}))
                        cloud_voice.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
                        cloud_voice.get_by_role("button", name="问助教", exact=True).click()
                        expect(cloud_voice.locator("#pet-memory-status")).to_be_hidden()
                        self.assertEqual(session_requests, [])
                        cloud_prompt = cloud_voice.get_by_role("textbox", name="问助教")
                        cloud_prompt.fill("你好")
                        with cloud_voice.expect_response("**/api/pet/sessions") as session:
                            cloud_prompt.press("Enter")
                        expect(cloud_voice.locator("#pet-reply")).to_contain_text("你好呀")
                        self.assertEqual(len(pending_config), 1)
                        config = pending_config[0].fetch().json()
                        config.update(voice=True, speech=True, speech_voices=["xiaoya"])
                        with cloud_voice.expect_request("**/api/pet/speech") as early_reply:
                            pending_config[0].fulfill(json=config)
                        self.assertIn("你好呀", early_reply.value.post_data_json["text"])
                        self.assertEqual(early_reply.value.post_data_json["voice"], "xiaoya")
                        expect(cloud_voice.locator("#pet-voice-status")).to_contain_text("朗读测试服务暂不可用")
                        cloud_voice.get_by_label("自动朗读").uncheck()
                        expect(cloud_voice.get_by_role("button", name="运行实验")).to_be_enabled()
                        cloud_prompt.focus()
                        cloud_voice.keyboard.press("t", delay=350)
                        expect(cloud_prompt).to_have_value("t")
                        expect(cloud_voice.locator("#pet-mic")).to_have_text("语音输入")
                        cloud_prompt.clear()
                        cloud_source = cloud_voice.locator("#source")
                        cloud_source.fill("")
                        cloud_source.press("t", delay=350)
                        expect(cloud_source).to_have_value("t")
                        expect(cloud_voice.locator("#pet-mic")).to_have_text("语音输入")
                        cloud_voice.get_by_role("button", name="收起", exact=True).click()
                        cloud_voice.keyboard.press("t")
                        expect(cloud_voice.locator("#pet-panel")).to_be_hidden()
                        cloud_voice.keyboard.down("t")
                        stop = cloud_voice.get_by_role("button", name="结束并转写")
                        expect(stop).to_be_visible()
                        expect(cloud_voice.locator("#pet-launch")).to_have_attribute("data-pose", "listen")
                        expect(cloud_voice.locator("#pet-panel meter")).to_have_count(0)
                        expect(cloud_voice.locator("#pet-voice-status")).to_contain_text("录音")
                        # The fake microphone supplies real-time audio to MediaRecorder.
                        cloud_voice.wait_for_timeout(850)
                        cloud_voice.keyboard.down("t")
                        expect(stop).to_be_visible()
                        with cloud_voice.expect_request("**/api/pet/voice"):
                            cloud_voice.keyboard.up("t")
                        expect(cloud_prompt).to_have_value("")
                        expect(cloud_voice.locator("#pet-heard")).to_have_text(
                            "听到「我的学习进驻怎样」，按「我的学习进度怎样」理解。")
                        expect(cloud_voice.locator("#pet-reply")).to_contain_text("概念题答对 0/0 次")
                        stale = session.value.url + "/" + session.value.json()["id"]
                        self.assertEqual(cloud_voice.request.post(stale + "/close").status, 200)
                        cloud_prompt.fill("现在的学习进度")
                        with cloud_voice.expect_response("**/api/pet/sessions") as renewed:
                            cloud_voice.get_by_role("button", name="发送", exact=True).click()
                        self.assertEqual(renewed.value.status, 201)
                        expect(cloud_voice.locator("#pet-reply")).to_contain_text("概念题答对 0/0 次")
                        selected = cloud_voice.locator("#pet-mic-device")
                        expect(selected).to_be_visible()
                        hardware = selected.locator("option").nth(1).get_attribute("value")
                        selected.select_option(hardware)
                        cloud_voice.get_by_role("button", name="语音输入", exact=True).click()
                        expect(stop).to_be_visible()
                        self.assertEqual(cloud_voice.evaluate("() => window.lastCapture.deviceId.exact"), hardware)
                        cloud_voice.wait_for_timeout(850)
                        stop.click()
                        expect(cloud_voice.locator("#pet-voice-status")).to_contain_text("几乎没有收到声音")
                        cloud_voice.evaluate("""id => {
                          window.removedMicrophone = id;
                          navigator.mediaDevices.dispatchEvent(new Event("devicechange"));
                        }""", hardware)
                        expect(cloud_voice.locator("#pet-voice-status")).to_contain_text("所选麦克风已断开")
                        expect(selected).to_have_value("")
                        cloud_voice.get_by_role("button", name="语音输入", exact=True).click()
                        expect(stop).to_be_visible()
                        cloud_voice.evaluate("() => window.lastInputTrack.dispatchEvent(new Event('ended'))")
                        expect(cloud_voice.locator("#pet-voice-status")).to_contain_text("录音设备已断开")
                        cloud_voice.evaluate("() => { window.denyMicrophone = true; }")
                        cloud_voice.get_by_role("button", name="语音输入", exact=True).click()
                        expect(cloud_voice.locator("#pet-voice-status")).to_contain_text("本站权限")
                        invalid = cloud_voice.request.post("http://127.0.0.1:8000/api/pet/voice",
                                                           data=b"\0" * 131073, headers={"Content-Type": "audio/webm"})
                        self.assertEqual(invalid.status, 413)
                    finally:
                        cloud_voice.close()
                    if out := os.getenv("TRACE_SCREENSHOTS"):
                        Path(out).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=f"{out}/workspace.png", full_page=True)

                    page.get_by_role("button", name="故障样例").click()
                    if live:
                        page.get_by_label("请求 AI 提示").check()
                    held = []
                    def is_submission(request):
                        return request.method == "POST" and request.url.endswith("/api/runs")

                    page.route("**/api/runs", lambda route: held.append(route))
                    with page.expect_response(lambda response: is_submission(response.request)) as submitted:
                        with page.expect_request(is_submission):
                            code.press("Control+Enter")
                        page.get_by_role("button", name="正确样例").click()
                        expect(run).to_be_disabled()
                        expect(pet).to_have_attribute("data-mood", "working")
                        expect(pet).to_have_attribute("data-pose", "focus")
                        expect(portrait.locator(".pet-strip")).to_have_css("animation-name", "pet-frames", timeout=10000)
                        expect(pet_bubble).to_be_visible()
                        held[0].continue_()
                    page.unroute("**/api/runs")
                    run_id = submitted.value.json()["id"]
                    expect(page.get_by_role("heading", name="疑似在等待管道 EOF")).to_be_visible(timeout=30000)
                    expect(pet).to_have_attribute("data-mood", "review")
                    expect(pet_bubble).to_contain_text("有运行线索")
                    pet.click()
                    expect(pet_reply).to_contain_text("有运行线索")
                    if out:
                        page.screenshot(path=f"{out}/companion.png", full_page=True)
                    pet_panel.get_by_role("button", name="打开 DeepSeek 提示" if live else "打开分层提示").click()
                    expect(page.get_by_role("button", name="分层提示", exact=True)).to_have_attribute("aria-pressed", "true")
                    page.get_by_role("button", name="测试判定").click()
                    page.get_by_role("button", name="查看关联事件").click()
                    expect(page.locator(".event.evidence").first).to_be_visible()
                    expect(page.get_by_role("link", name="原始日志")).to_be_visible()
                    expect(pet_bubble).to_contain_text("系统调用轨迹")
                    ask = page.locator(".event.evidence").get_by_role("button", name=re.compile("问助教")).first
                    event_number = ask.get_attribute("aria-label").split()[-1]
                    ask.click()
                    expect(pet_reply).to_contain_text("事件 #" + event_number)
                    prompt.fill("这条调用是什么意思")
                    prompt.press("Enter")
                    expect(pet_reply).to_contain_text("事件 #" + event_number)
                    pet_panel.get_by_role("button", name="收起").click()
                    if out:
                        page.screenshot(path=f"{out}/evidence.png", full_page=True)
                    page.get_by_role("button", name="分层提示").click()
                    if live:
                        report = page.request.get(f"http://127.0.0.1:8000/api/runs/{run_id}").json()["result"]
                        feedback = report["feedback"]
                        self.assertEqual(feedback["source"], "ai", feedback.get("reason"))
                        self.assertEqual(set(feedback["evidence"]), set(report["diagnosis"]["evidence"]))
                        self.assertEqual(len(feedback["hints"]), 3)
                        expect(page.get_by_text("AI · " + feedback["model"], exact=True)).to_be_visible()
                        print(json.dumps({"model": feedback["model"], "usage": feedback["usage"],
                                          "duration_ms": feedback["duration_ms"],
                                          "verified_evidence": len(feedback["evidence"])}, ensure_ascii=False))
                        page.get_by_label("请求 AI 提示").uncheck()
                    else:
                        expect(page.get_by_text("规则提示", exact=True)).to_be_visible()
                    expect(page.get_by_text("证据定位", exact=True)).to_be_visible()
                    pet.click()
                    prompt.fill("刚才那条调用是什么")
                    prompt.press("Enter")
                    expect(pet_reply).to_contain_text("事件 #" + event_number)
                    pet_panel.get_by_role("button", name="收起").click()

                    page.get_by_role("button", name="正确样例").click()
                    run.click()
                    expect(page.get_by_text("2 / 2 通过", exact=True)).to_be_visible(timeout=30000)
                    expect(pet).to_have_attribute("data-mood", "success")
                    expect(pet_bubble).to_contain_text("全部用例通过")
                    pet.click()
                    pet_panel.get_by_role("button", name="学习进度").click()
                    expect(pet_reply).to_contain_text("评测 2 次")
                    expect(pet_reply).to_contain_text("最近一次通过 2/2")
                    expect(pet_reply).to_contain_text("概念题答对 1/2 次")
                    pet_panel.get_by_role("button", name="本轮回顾").click()
                    expect(pet_reply).to_contain_text("完成 2 次评测、2 次小测作答")
                    expect(pet_reply).to_contain_text("最近关注的是事件 #" + event_number)
                    pet_panel.get_by_role("button", name="查看诊断复盘").click()
                    review = page.locator(".review-steps")
                    expect(review.get_by_text("0/2 → 2/2 用例通过。", exact=False)).to_be_visible(timeout=15000)
                    expect(review.get_by_text("运行超时 → 通过", exact=False)).to_be_visible()
                    evidence_link = review.get_by_role("button", name=re.compile(r"^#\d+ ·")).first
                    evidence_id = evidence_link.inner_text().split(" ", 1)[0]
                    evidence_link.click()
                    focused = page.locator(".event.evidence:focus")
                    expect(focused).to_contain_text(evidence_id + " ·")
                    page.get_by_role("button", name="诊断复盘", exact=True).click()
                    review.get_by_role("button", name="打开后一次运行").click(timeout=15000)
                    expect(page.locator("#status")).to_have_text("2 / 2 通过")
                    page.get_by_role("button", name="演示自检", exact=True).click()
                    demo = page.get_by_role("dialog", name="演示自检")
                    with page.expect_response("**/api/demo-check", timeout=45000) as health:
                        demo.get_by_role("button", name="开始自检").click()
                    checks = {check["name"]: check for check in health.value.json()["checks"]}
                    self.assertEqual(checks["沙箱编译与运行"]["state"], "ready")
                    self.assertEqual(checks["系统调用观测"]["state"], "ready")
                    self.assertEqual(checks["DeepSeek 提示"]["state"], "configured" if live else "missing")
                    expect(demo.get_by_text("自检完成。")).to_be_visible()
                    if live:
                        demo.get_by_label("同时实测 Xiaoyi 和 DeepSeek").check()
                        with page.expect_response("**/api/demo-check", timeout=45000) as online_check:
                            demo.get_by_role("button", name="开始自检").click()
                        model_check = next(row for row in online_check.value.json()["checks"]
                                           if row["name"] == "DeepSeek 提示")
                        self.assertEqual(model_check["state"], "ready", model_check["detail"])
                    demo.get_by_role("button", name="关闭").click()
                    page.get_by_role("button", name="实验记录").click()
                    expect(page.locator("tbody tr")).to_have_count(2)
                    page.get_by_role("button", name="对比最近两次").click()
                    compare = page.locator("#comparison")
                    expect(compare.get_by_role("heading", name="进程与管道 · 前后对比")).to_be_visible()
                    expect(compare.get_by_text("0 / 2 用例通过", exact=False)).to_be_visible()
                    expect(compare.get_by_text("2 / 2 用例通过", exact=False)).to_be_visible()
                    expect(compare.get_by_text("常规用例 · 运行超时")).to_be_visible()
                    expect(compare.get_by_text("边界用例 · 通过")).to_be_visible()
                    if out:
                        page.screenshot(path=f"{out}/comparison.png", full_page=True)
                    compare.get_by_role("button", name="查看关联事件").click()
                    expect(page.locator(".event.evidence").first).to_be_visible()
                    page.get_by_role("button", name="实验记录").click()
                    page.get_by_role("button", name="查看", exact=True).last.click()
                    expect(page.get_by_role("heading", name="疑似在等待管道 EOF")).to_be_visible()

                    page.get_by_role("textbox", name="C 源代码").fill("int main(void) {for (;;) {}}")
                    with page.expect_response(lambda response: is_submission(response.request)) as unknown:
                        run.click()
                    unknown_id = unknown.value.json()["id"]
                    expect(page.get_by_role("heading", name="超过运行时限")).to_be_visible(timeout=30000)
                    expect(page.get_by_text("证据不足", exact=False)).to_be_visible()
                    expect(page.get_by_text("用例输入", exact=True).first).to_be_visible()
                    page.get_by_role("button", name="诊断复盘", exact=True).click()
                    expect(review.get_by_text("证据不足", exact=False)).to_be_visible(timeout=15000)
                    expect(review.get_by_role("button", name=re.compile(r"^#\d+ ·"))).to_have_count(0)
                    with page.expect_response(lambda response: "page=last" in response.url) as tail:
                        page.get_by_role("button", name="查看末尾轨迹").click()
                    self.assertGreater(tail.value.json()["total"], 0)
                    expect(page.locator(".event").last).to_be_visible()
                    expect(page.get_by_role("button", name="下一页")).to_be_disabled()
                    bad_path = f"http://127.0.0.1:8000/api/runs/{unknown_id}/events/" + "9" * 4500
                    self.assertEqual(page.request.get(bad_path).status, 404)
                    page.set_viewport_size({"width": 390, "height": 844})
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    page.emulate_media(reduced_motion="reduce")
                    pet.hover()
                    expect(portrait).to_have_css("animation-name", "none")
                    expect(pet).to_have_css("transition-duration", "0s")
                    expect(pet).not_to_have_attribute("data-roaming", "true")
                    pet.click()
                    self.assertGreaterEqual(pet_panel.bounding_box()["x"], 0)
                    self.assertLessEqual(pet_panel.bounding_box()["x"] + pet_panel.bounding_box()["width"], 390)
                    if out:
                        page.screenshot(path=f"{out}/mobile.png", full_page=True)
                    self.assertEqual(errors, [])
                    self.assertTrue(session_ids)
                    session_url = "http://127.0.0.1:8000/api/pet/sessions/" + session_ids[-1]
                    self.assertEqual(context.request.get(session_url).status, 200)
                    page.close()
                    fresh = context.new_page()
                    fresh.goto("http://127.0.0.1:8000")
                    expect(fresh.get_by_role("button", name="运行实验")).to_be_enabled()
                    fresh.get_by_role("button", name="小助教", exact=True).click()
                    fresh.get_by_role("button", name="本轮回顾").click()
                    expect(fresh.locator("#pet-reply")).to_contain_text("完成 0 次评测、0 次小测作答，提出 0 个问题")
                    deadline = monotonic() + 4
                    while context.request.get(session_url).status != 404:
                        self.assertLess(monotonic(), deadline, "closing the tab did not delete its study session")
                        sleep(.1)
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
