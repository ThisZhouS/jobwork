"""采集 brandIndustry -> industry 码映射（用于 --industry 参数）。"""
import json
import time
from pathlib import Path

from boss_crawler.session import BossBrowser, human_sleep

API = (
    "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
    "?scene=1&query={q}&city=100010000&page=1&pageSize=30"
)
JS = """async (url) => {
    const r = await fetch(url, {credentials: 'include', headers: {'x-requested-with': 'XMLHttpRequest'}});
    const j = await r.json().catch(() => ({}));
    const list = (j.zpData && j.zpData.jobList) || [];
    return { code: j.code, items: list.map(x => [x.industry, x.brandIndustry]) };
}"""

KEYWORDS = [
    "Python", "Java", "前端", "算法", "测试", "运维", "产品经理", "UI设计",
    "电商", "医疗", "云计算", "教育", "广告", "物联网", "零售", "游戏",
    "银行", "保险", "汽车", "物流", "制造", "餐饮", "房地产", "人力资源",
]

pairs: dict[str, int] = {}
with BossBrowser(headless=False) as browser:
    page = browser.page()
    browser.goto(page, "https://www.zhipin.com/web/geek/jobs?city=100010000")
    time.sleep(3)

    for i, kw in enumerate(KEYWORDS, start=1):
        res = page.evaluate(JS, API.format(q=kw))
        code = res.get("code")
        if code != 0:
            print(f"[{i}/{len(KEYWORDS)}] {kw}: code={code}，退避后重试")
            human_sleep((10, 20))
            browser.goto(page, "https://www.zhipin.com/web/geek/jobs?city=100010000")
            time.sleep(2)
            res = page.evaluate(JS, API.format(q=kw))
        for industry, name in res.get("items", []):
            if isinstance(industry, int) and name:
                pairs.setdefault(name.strip(), industry)
        print(f"[{i}/{len(KEYWORDS)}] {kw}: +{len(res.get('items', []))} items, total labels={len(pairs)}")
        human_sleep((2.0, 3.5))

out = Path(__file__).with_name("industry_codes.json")
out.write_text(json.dumps(dict(sorted(pairs.items(), key=lambda kv: kv[1])), ensure_ascii=False, indent=1), encoding="utf-8")
print("saved", out, len(pairs), "labels")
