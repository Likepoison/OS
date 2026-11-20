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
                    page = browser.new_page(viewport={"width": 1440, "height": 960})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.route("**/api/labs", lambda route: route.fulfill(
                        status=200, content_type="text/html", body="<p>Sign in to continue</p>"))
                    page.goto("http://127.0.0.1:8000")
                    expect(page.get_by_role("alert")).to_contain_text("从 Ports 重新打开私有预览")
                    expect(page.get_by_role("button", name="运行实验")).to_be_disabled()
                    page.unroute("**/api/labs")
                    page.reload()
                    expect(page).to_have_title("循迹 OS · 操作系统实验工作台")
                    run = page.get_by_role("button", name="运行实验")
                    expect(run).to_be_enabled()
                    pet = page.get_by_role("button", name="鲸鱼娘助教")
                    pet_panel = page.get_by_role("complementary", name="鲸鱼娘助教")
                    portrait = pet.locator("img")
                    expect(portrait).to_have_attribute("src", "/pet/whale-girl.png")
                    self.assertEqual(portrait.evaluate("(img) => img.naturalWidth"), 144)
                    pet_bubble = page.locator("#pet-bubble")
                    expect(pet_bubble).to_be_visible()
                    expect(pet_bubble).to_contain_text("我是鲸鱼娘助教")
                    page.emulate_media(reduced_motion="no-preference")
                    pet.hover()
                    expect(portrait).to_have_css("transform", re.compile(r"^matrix\("))
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
                    expect(pet_panel.get_by_role("status")).to_contain_text("再想一步")
                    pet_panel.get_by_role("button", name="最后一个写端被关闭后").click()
                    expect(pet_panel.get_by_role("status")).to_contain_text("答对啦")
                    user_text = "<b>无关内容</b>"
                    requests = []
                    def collect(request):
                        requests.append(request)

                    page.on("request", collect)
                    pet_panel.get_by_role("textbox", name="问鲸鱼娘").fill(user_text)
                    pet_panel.get_by_role("textbox", name="问鲸鱼娘").press("Enter")
                    expect(pet_panel.get_by_role("status")).to_contain_text("我可以陪你看本次结果")
                    self.assertNotIn(user_text, pet_panel.inner_text())
                    self.assertTrue(all(req.method == "GET" and "/pet/" in req.url for req in requests))
                    page.remove_listener("request", collect)
                    pet_panel.get_by_role("button", name="回到角落").click()
                    self.assertEqual(pet.bounding_box()["x"], original["x"])
                    pet_panel.get_by_role("button", name="隐藏桌宠").click()
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
                            run.click()
                        page.get_by_role("button", name="正确样例").click()
                        expect(run).to_be_disabled()
                        expect(pet).to_have_attribute("data-mood", "working")
                        expect(portrait).to_have_css("animation-name", "pet-work")
                        expect(pet_bubble).to_be_visible()
                        held[0].continue_()
                    page.unroute("**/api/runs")
                    run_id = submitted.value.json()["id"]
                    expect(page.get_by_role("heading", name="疑似在等待管道 EOF")).to_be_visible(timeout=30000)
                    expect(pet).to_have_attribute("data-mood", "review")
                    expect(pet_bubble).to_contain_text("有运行线索")
                    pet.click()
                    expect(pet_panel.get_by_role("status")).to_contain_text("有运行线索")
                    if out:
                        page.screenshot(path=f"{out}/companion.png", full_page=True)
                    pet_panel.get_by_role("button", name="打开 DeepSeek 提示" if live else "打开分层提示").click()
                    expect(page.get_by_role("button", name="分层提示", exact=True)).to_have_attribute("aria-pressed", "true")
                    page.get_by_role("button", name="测试判定").click()
                    page.get_by_role("button", name="查看关联事件").click()
                    expect(page.locator(".event.evidence").first).to_be_visible()
                    expect(page.get_by_role("link", name="原始日志")).to_be_visible()
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

                    page.get_by_role("button", name="正确样例").click()
                    run.click()
                    expect(page.get_by_text("2 / 2 通过", exact=True)).to_be_visible(timeout=30000)
                    expect(pet).to_have_attribute("data-mood", "success")
                    expect(pet_bubble).to_contain_text("全部用例通过")
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
                    expect(portrait).to_have_css("transform", "none")
                    expect(portrait).to_have_css("animation-name", "none")
                    pet.click()
                    self.assertGreaterEqual(pet_panel.bounding_box()["x"], 0)
                    self.assertLessEqual(pet_panel.bounding_box()["x"] + pet_panel.bounding_box()["width"], 390)
                    if out:
                        page.screenshot(path=f"{out}/mobile.png", full_page=True)
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
