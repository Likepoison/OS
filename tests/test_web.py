import json
import os
from pathlib import Path
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
                    page.goto("http://127.0.0.1:8000")
                    run = page.get_by_role("button", name="运行实验")
                    expect(run).to_be_enabled()
                    if out := os.getenv("TRACE_SCREENSHOTS"):
                        Path(out).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=f"{out}/workspace.png", full_page=True)

                    page.get_by_role("button", name="故障样例").click()
                    if live:
                        page.get_by_label("请求 AI 提示").check()
                    with page.expect_response(lambda response: response.request.method == "POST" and
                                              response.url.endswith("/api/runs")) as submitted:
                        run.click()
                    run_id = submitted.value.json()["id"]
                    expect(page.get_by_role("heading", name="疑似在等待管道 EOF")).to_be_visible(timeout=30000)
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
                    page.get_by_role("button", name="实验记录").click()
                    expect(page.locator("tbody tr")).to_have_count(2)
                    page.get_by_role("button", name="对比最近两次").click()
                    expect(page.get_by_role("heading", name="进程与管道 · 前后对比")).to_be_visible()
                    expect(page.locator("#comparison").get_by_text("0 / 2 用例通过", exact=False)).to_be_visible()
                    expect(page.locator("#comparison").get_by_text("2 / 2 用例通过", exact=False)).to_be_visible()
                    if out:
                        page.screenshot(path=f"{out}/comparison.png", full_page=True)
                    page.get_by_role("button", name="查看", exact=True).last.click()
                    expect(page.get_by_role("heading", name="疑似在等待管道 EOF")).to_be_visible()

                    page.set_viewport_size({"width": 390, "height": 844})
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    if out:
                        page.screenshot(path=f"{out}/mobile.png", full_page=True)
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
