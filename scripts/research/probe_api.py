"""Probe: can an anonymous stealth session reach zhipin's job-list JSON API?"""
import json
from scrapling.fetchers import StealthySession

API = (
    "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
    "?scene=1&query=Python&city=101270100&page=1&pageSize=30"
)

JS = """async (api) => {
    try {
        const r = await fetch(api, {credentials: 'include', headers: {'x-requested-with': 'XMLHttpRequest'}});
        const t = await r.text();
        return {status: r.status, ct: r.headers.get('content-type'), body: t.slice(0, 500)};
    } catch (e) { return {error: String(e)}; }
}"""


def page_action(page):
    out = page.evaluate(JS, API)
    open("probe_api_out.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))


with StealthySession(
    headless=False,
    locale="zh-CN",
    timezone_id="Asia/Shanghai",
    wait=2000,
    timeout=60000,
    page_action=page_action,
) as session:
    resp = session.fetch("https://www.zhipin.com/")
    print("HOME STATUS:", resp.status, resp.url)

print(open("probe_api_out.json", encoding="utf-8").read()[:1200])
