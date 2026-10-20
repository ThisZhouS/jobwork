"""Probe: scrapling StealthySession against zhipin (no cookies)."""
import json, sys, time
from scrapling.fetchers import StealthySession

URL = "https://www.zhipin.com/web/geek/job?query=Python&city=101270100"

headless = "--headless" in sys.argv
with StealthySession(
    headless=headless,
    locale="zh-CN",
    timezone_id="Asia/Shanghai",
    real_chrome=False,
    wait=4000,
    network_idle=True,
    timeout=60000,
) as session:
    resp = session.fetch(URL)
    print("STATUS:", resp.status)
    print("URL:", resp.url)
    print("BODY LEN:", len(resp.html_content or ""))
    text = resp.get_all_text(ignore_tags=("script", "style"))
    print("TEXT LEN:", len(text))
    print("TEXT[:500]:", text[:500].replace("\n", " | "))
    # xhr log if captured
    xhr = getattr(resp, "xhr", None)
    if xhr:
        print("XHR count:", len(xhr))
        for item in list(xhr)[:10]:
            print(" ", str(item)[:200])
    open("probe_scrapling.html", "w", encoding="utf-8").write(resp.html_content or "")


