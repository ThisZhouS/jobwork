"""探测：列表页筛选参数是怎么传到接口的，以及参数名/取值是否有效。"""
import json
import time

from boss_crawler import config
from boss_crawler.session import BossBrowser

FILTER_URL = (
    "https://www.zhipin.com/web/geek/jobs"
    "?query=Python&city=101270100&salary=406&experience=105&degree=203"
)

JS = """async (url) => {
    const r = await fetch(url, {credentials: 'include', headers: {'x-requested-with': 'XMLHttpRequest'}});
    const j = await r.json().catch(() => ({}));
    const list = (j.zpData && j.zpData.jobList) || [];
    return {
        code: j.code, msg: j.message, count: list.length,
        filterString: j.zpData && j.zpData.filterString,
        sample: list.slice(0, 6).map(x => [x.jobName, x.salaryDesc, x.jobExperience, x.jobDegree])
    };
}"""

BASE = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?scene=1&query=Python&city=101270100&page=1&pageSize=30"

with BossBrowser(headless=False) as browser:
    page = browser.page()
    captured = []
    page.on("request", lambda r: captured.append((r.method, r.url, r.post_data)) if "joblist.json" in r.url else None)

    browser.goto(page, FILTER_URL)
    time.sleep(6)

    print("== SPA 发出的 joblist 请求 ==")
    for method, url, body in captured[-3:]:
        print(f"  {method} {url}")
        if body:
            print(f"    body={body[:300]}")

    print("\n== 页面筛选状态 ==")
    print(page.evaluate("() => document.querySelector('.filter-condition')?.innerText.replace(/\\n+/g,' | ')")[:300])
    print("cards:", page.evaluate("() => document.querySelectorAll('.job-card-box').length"))

    print("\n== 直接调接口：无筛选 ==")
    print(json.dumps(page.evaluate(JS, BASE), ensure_ascii=False)[:600])

    print("\n== 直接调接口：带 salary/experience/degree ==")
    print(json.dumps(page.evaluate(JS, BASE + "&salary=406&experience=105&degree=203"), ensure_ascii=False)[:600])
