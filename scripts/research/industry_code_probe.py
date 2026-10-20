"""探测：industry 参数是否接受职位数据里的数字行业码。"""
import json
import time

from boss_crawler.session import BossBrowser

BASE = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?scene=1&query=Python&city=101270100&page=1&pageSize=30"

JS = """async (url) => {
    const r = await fetch(url, {credentials: 'include', headers: {'x-requested-with': 'XMLHttpRequest'}});
    const j = await r.json().catch(() => ({}));
    const list = (j.zpData && j.zpData.jobList) || [];
    return {
        code: j.code, count: list.length,
        items: list.slice(0, 40).map(x => [x.industry, x.brandIndustry]),
    };
}"""

with BossBrowser(headless=False) as browser:
    page = browser.page()
    browser.goto(page, "https://www.zhipin.com/web/geek/jobs?query=Python&city=101270100")
    time.sleep(3)

    plain = page.evaluate(JS, BASE)
    pairs = sorted({tuple(i) for i in plain["items"]})
    print("unfiltered industry codes:", pairs[:20])

    for code in (100305, 100020, 100101):
        res = page.evaluate(JS, BASE + f"&industry={code}")
        codes = sorted({i[0] for i in res["items"]})
        print(f"industry={code}: count={res['count']} codes={codes[:8]}")
        time.sleep(1.5)
