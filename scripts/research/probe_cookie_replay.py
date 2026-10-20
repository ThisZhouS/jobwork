"""Probe: does the visible (non-httpOnly) zhipin cookie set already carry the login?

Reads the cookie string captured by tools/cookie_bridge.py from .state/bridge.txt and
replays it in a fresh stealth browser, then asks the account-status API who we are.
Never prints cookie values.
"""
import json
import pathlib
import time

from scrapling.fetchers import StealthySession

COOKIES_FILE = pathlib.Path(".state/bridge.txt")


def load_cookies():
    raw = COOKIES_FILE.read_text(encoding="utf-8").strip()
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        out.append({"name": name, "value": value, "domain": ".zhipin.com", "path": "/"})
    return out


STATUS_JS = """async () => {
    const r = await fetch('https://www.zhipin.com/wapi/zpuser/h5/account/getStatus', {credentials: 'include'});
    const j = await r.json().catch(() => ({}));
    return {code: j.code, message: j.message, zpData: j.zpData};
}"""

with StealthySession(
    headless=False,
    locale="zh-CN",
    timezone_id="Asia/Shanghai",
    cookies=load_cookies(),
    wait=1500,
    timeout=60000,
) as session:
    page = session.context.new_page()
    page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    out = page.evaluate(STATUS_JS)
    print("ACCOUNT:", json.dumps(out, ensure_ascii=False)[:300])
    print("COOKIE NAMES:", sorted({c["name"] for c in session.context.cookies()}))
