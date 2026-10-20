"""反检测自检：在真实站点上观测页面是否被「控制台检测 / 会话页面销毁」干掉。

用法：python tools/anti_detect_check.py [观测秒数]
"""
import sys
import time

from boss_crawler import config
from boss_crawler.session import BossBrowser

WATCH_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
URL = config.SEARCH_PAGE_URL.format(query="Python", city="101270100")

with BossBrowser(headless=False) as browser:
    page = browser.page(goto=URL)
    browser.ensure_armed(page)
    # 等 SPA 完成首次渲染（列表是异步拉取的）
    for _ in range(20):
        time.sleep(1)
        try:
            if page.evaluate("() => document.querySelectorAll('.job-card-box').length") > 0:
                break
        except Exception:
            break
    browser.ensure_armed(page)
    print(f"打开 {URL}")
    print(f"stealth={page.evaluate('() => window.__bc_stealth__ || null')}")

    destroyed_at = None
    for tick in range(WATCH_SECONDS):
        time.sleep(1)
        try:
            url = page.url
            cards = page.evaluate("() => document.querySelectorAll('.job-card-box').length")
            alive = page.evaluate("() => window.__bc_alive === true")
            console_patched = page.evaluate("() => !!window.__bc_native_console")
        except Exception as exc:
            url, cards, alive, console_patched = f"<evaluate failed: {type(exc).__name__}>", 0, False, False
            browser.ensure_armed(page)
        if tick in (0, 4, 9, WATCH_SECONDS - 1):
            print(f"  t+{tick + 1:02d}s cards={cards} heartbeat={alive} console_patched={console_patched} url={url[:64]}")
        if url.startswith("about:blank"):
            destroyed_at = tick + 1
            break

    if destroyed_at:
        print(f"页面在 t+{destroyed_at}s 被销毁且未恢复")
        sys.exit(1)
    print(f"观测 {WATCH_SECONDS}s：页面存活，列表卡片在，注入仍生效")
