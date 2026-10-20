"""Dump the shape of the job-detail API response so the parser can be precise."""
import json
from pathlib import Path

from boss_crawler import config
from boss_crawler.crawler import FETCH_JS
from boss_crawler.session import BossBrowser

rows = [json.loads(line) for line in Path("output/jobs_Python_成都_20261019_145405.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
job = rows[0]
url = config.JOB_DETAIL_API.format(security_id=job["security_id"], lid=job.get("lid", ""))


def prune(obj, depth=0):
    if depth > 2:
        return "…"
    if isinstance(obj, dict):
        return {k: prune(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [prune(x, depth + 1) for x in obj[:3]] + (["…"] if len(obj) > 3 else [])
    if isinstance(obj, str):
        return obj[:120]
    return obj


with BossBrowser(headless=False) as browser:
    page = browser.page()
    browser.goto(page, config.SEARCH_PAGE_URL.format(query="Python", city="101270100"))
    browser.ensure_armed(page)
    result = page.evaluate(FETCH_JS, url)
    payload = result.get("json") or {}
    print("code:", payload.get("code"), payload.get("message"))
    print(json.dumps(prune(payload.get("zpData") or {}), ensure_ascii=False, indent=1)[:6000])
