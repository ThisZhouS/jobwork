"""Smoke test: start the stealth browser, open the login page, verify patches."""
import json
import time
from pathlib import Path

from boss_crawler import config
from boss_crawler.session import BossBrowser

OUT = config.OUTPUT_DIR / "login.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

with BossBrowser(headless=False) as browser:
    page = browser.page(goto=config.LOGIN_URL)
    time.sleep(3)
    info = page.evaluate("""() => ({
        stealth: window.__bc_stealth__ || null,
        closeIsNoop: /function\\s*\\(\\)\\s*\\{\\s*\\}/.test(String(window.close)) || window.close.length === 0,
        tablePatched: String(console.table).includes('() => {}') || String(console.table).length < 40,
        nativeConsole: !!window.__bc_native_console,
        heartbeat: !!window.__bc_heartbeat,
        webdriver: navigator.webdriver,
        url: location.href,
        title: document.title,
    })""")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    page.screenshot(path=str(OUT))
    print("screenshot:", OUT)
    print("cookies:", sorted(browser.cookie_names()))
    print("logged_in:", browser.is_logged_in(verify=False))
