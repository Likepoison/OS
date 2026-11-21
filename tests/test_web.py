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
                    browser = runtime.chromium.launch()
                    context = browser.new_context(viewport={"width": 1440, "height": 960})
                    page = context.new_page()
                    session_ids = []
                    page.add_init_script("""
                        window.SpeechRecognition = class {
                          start() { window.currentDictation = this; }
                          stop() {}
                          abort() { this.cancelled = true; }
                        };
                        window.speechSynthesis.speak = utterance => {
                          window.lastSpokenReply = utterance.text;
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
                    page.reload()
                    expect(page).to_have_title("TraceTutor——操作系统实验评测与智能诊断平台")
                    expect(page.locator(".brand")).to_contain_text("TraceTutor")
                    run = page.get_by_role("button", name="运行实验")
                    expect(run).to_be_enabled()
                    self.assertEqual(page.locator(".grid > .panel").evaluate_all(
                        "(nodes) => new Set(nodes.map(n => n.getBoundingClientRect().bottom)).size"), 1)
                    self.assertTrue(page.locator("#quote-source").get_attribute("href").startswith("https://"))
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
                    options.get_by_label("字号").select_option("17")
                    options.get_by_label("制表符宽度").select_option("2")
                    options.get_by_label("自动换行").check()
                    expect(code).to_have_css("font-size", "17px")
                    expect(code).to_have_css("tab-size", "2")
                    expect(code).to_have_attribute("wrap", "soft")
                    expect(code).to_have_value(original_code)
                    options.get_by_label("自动换行").uncheck()
                    options.get_by_role("button", name="完成").click()
                    pet = page.get_by_role("button", name="鲸鱼娘助教")
                    pet_panel = page.get_by_role("complementary", name="鲸鱼娘助教")
                    pet_reply = pet_panel.locator("#pet-reply")
                    portrait = pet.locator(".pet-figure")
                    expect(portrait).to_have_css("background-image", re.compile("whale-actions.webp"))
                    self.assertEqual(page.evaluate("""async () => {
                      const image = new Image();
                      image.src = '/pet/whale-actions.webp';
                      await image.decode();
                      return [image.naturalWidth, image.naturalHeight];
                    }"""), [1216, 1064])
                    pet_bubble = page.locator("#pet-bubble")
                    self.assertGreater(portrait.bounding_box()["width"], 100)
                    expect(pet).to_have_css("background-color", "rgba(0, 0, 0, 0)")
                    page.emulate_media(reduced_motion="no-preference")
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
                    prompt = pet_panel.get_by_role("textbox", name="问鲸鱼娘")
                    voice.click()
                    expect(pet_panel.get_by_role("button", name="停止聆听")).to_be_visible()
                    page.evaluate("""window.currentDictation.onresult({
                        resultIndex: 0, results: [[{transcript: "我的学习进度怎样"}]]
                    })""")
                    expect(prompt).to_have_value("我的学习进度怎样")
                    expect(pet_reply).to_contain_text("答对啦")
                    pet_panel.get_by_label("自动朗读").check()
                    prompt.press("Enter")
                    expect(pet_reply).to_contain_text("概念题答对 1/2 次")
                    self.assertIn("概念题答对 1/2 次", page.evaluate("window.lastSpokenReply"))
                    voice.click()
                    page.evaluate("window.currentDictation.onerror({error:'not-allowed'})")
                    expect(pet_panel.locator("#pet-voice-status")).to_contain_text("可以继续打字")
                    user_text = "<b>无关内容</b>"
                    requests = []
                    def collect(request):
                        requests.append(request)

                    page.on("request", collect)
                    pet_panel.get_by_role("textbox", name="问鲸鱼娘").fill(user_text)
                    pet_panel.get_by_role("textbox", name="问鲸鱼娘").press("Enter")
                    expect(pet_reply).to_contain_text("我可以陪你看本次结果")
                    self.assertNotIn(user_text, pet_panel.inner_text())
                    self.assertTrue(all("/api/pet/sessions" in req.url or
                                        (req.method == "GET" and "/pet/" in req.url) for req in requests))
                    self.assertEqual(page.evaluate("localStorage.length + sessionStorage.length"), 0)
                    page.remove_listener("request", collect)
                    pet_panel.get_by_role("button", name="回到角落").click()
                    self.assertEqual(pet.bounding_box()["x"], original["x"])
                    voice.click()
                    pet_panel.get_by_role("button", name="隐藏桌宠").click()
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
                        pending_art = []
                        mobile.route("**/pet/whale-actions.webp", lambda route: pending_art.append(route))
                        with mobile.expect_request("**/pet/whale-actions.webp"):
                            mobile.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
                        mobile_pet = mobile.locator("#pet-launch")
                        expect(mobile_pet.locator(".pet-figure")).to_have_css("background-image", re.compile("whale-stand.webp"))
                        self.assertTrue(pending_art)
                        pending_art[0].continue_()
                        expect(mobile_pet).to_have_attribute("data-figure", "ready")
                        expect(mobile.locator("#pet-bubble")).to_contain_text("我是鲸鱼娘助教")
                        self.assertEqual(mobile.evaluate("document.documentElement.scrollWidth"), 390)
                        self.assertTrue(mobile.locator(".grid > .panel").evaluate_all(
                            "(nodes) => nodes[1].getBoundingClientRect().top > nodes[0].getBoundingClientRect().bottom"))
                        mobile.mouse.move(20, 120)
                        home = mobile_pet.bounding_box()["x"]
                        mobile.clock.run_for(12000)
                        expect(mobile_pet).to_have_attribute("data-roaming", "true")
                        self.assertLess(float(mobile_pet.evaluate("(el) => parseFloat(el.style.left)")), home - 40)
                        mobile.clock.run_for(10000)
                        expect(mobile_pet).to_have_attribute("data-pose", "sit")
                        mobile.clock.run_for(11000)
                        expect(mobile_pet).to_have_attribute("data-pose", "snack")
                        mobile.clock.run_for(11000)
                        expect(mobile_pet).to_have_attribute("data-pose", "play")
                        mobile.get_by_role("button", name="外观设置").click()
                        mobile.get_by_label("桌宠自由活动").uncheck()
                        mobile.get_by_label("桌宠主动气泡").uncheck()
                        mobile.get_by_role("button", name="完成").click()
                        mobile.clock.fast_forward(65000)
                        expect(mobile_pet).to_have_attribute("data-motion", "false")
                        expect(mobile.locator("#pet-bubble")).to_be_hidden()
                    finally:
                        mobile.close()
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
                        expect(portrait).to_have_css("animation-name", "pet-frames")
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
                    pet_panel.get_by_role("button", name="收起").click()
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
                    fresh.get_by_role("button", name="鲸鱼娘助教").click()
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
