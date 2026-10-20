"""Probe: how does zhipin react to a plain automated chromium (headful/headless)?"""
import sys, time, json
from playwright.sync_api import sync_playwright

URL = "https://www.zhipin.com/web/geek/job?query=Python&city=101270100"
headless = "--headless" in sys.argv

STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
"""

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--lang=zh-CN",
        ],
    )
    ctx = browser.new_context(
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={"width": 1600, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        ),
    )
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()
    msgs = []
    page.on("console", lambda m: msgs.append(f"{m.type}: {m.text}"[:300]))
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    for _ in range(6):
        time.sleep(2)
        n = page.locator(".job-card-wrapper").count()
        print(f"t+{(_+1)*2}s cards={n} url={page.url}")
        if n:
            break
    html = page.content()
    body_text = page.inner_text("body")
    print("TITLE:", page.title())
    print("FINAL URL:", page.url)
    print("BODY LEN:", len(body_text))
    print("HTML LEN:", len(html))
    print("TEXT[:400]:", body_text[:400].replace("\n", " | "))
    print("CONSOLE:", json.dumps(msgs[-15:], ensure_ascii=False))
    page.screenshot(path=f"probe_{'headless' if headless else 'headful'}.png")
    browser.close()
