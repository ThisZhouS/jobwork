"""抓取编排：SPA 预热 -> 列表接口分页 -> 详情接口 -> 落盘。

反爬应对策略（对应本次要求的两点）：
  * 控制台检测：stealth.js 把 console.table/clear 等探测变成空操作，页面里的
    「打印大对象 + 计时」探针拿不到 devtools 信号。
  * 会话页面销毁：stealth.js 拦掉 window.close / about:blank 跳转；本模块
    在每次请求前后做健康检查，页面真的没了就重建并重新预热，从当前页续跑。
  * 风控 code 37（「您的环境存在异常」）：退避后重新预热 SPA，让页面脚本重新
    签发 __zp_stoken__ 再重试；仍失败则报错让用户重新登录。
"""
from __future__ import annotations

import random
import time
from urllib.parse import urlencode

from .. import config
from ..filters import describe, resolve_filters
from .parser import parse_detail, parse_joblist, parse_joblist_dom
from .browser import BossBrowser, LoginRequired, PageDestroyed, human_sleep
from ..store.jsonl import JobStore

FETCH_JS = """async (url) => {
    try {
        const r = await fetch(url, {
            credentials: 'include',
            headers: {
                'x-requested-with': 'XMLHttpRequest',
                'accept': 'application/json, text/plain, */*',
            },
        });
        const text = await r.text();
        let json = null;
        try { json = JSON.parse(text); } catch (e) { json = null; }
        return {
            status: r.status,
            url: r.url,
            json: json,
            text: json ? '' : text.slice(0, 400),
        };
    } catch (e) {
        return {status: 0, error: String(e)};
    }
}"""

DOM_JS = "() => document.documentElement.outerHTML"

_DESTROY_MARKERS = (
    "Execution context was destroyed",
    "Target closed",
    "Target page, context or browser has been closed",
    "Page closed",
    "browser has disconnected",
)


class JobCrawler:
    def __init__(
        self,
        browser: BossBrowser,
        *,
        query: str,
        city: str,
        pages: int = 3,
        page_size: int = config.DEFAULT_PAGE_SIZE,
        with_detail: bool = False,
        take: int | None = None,
        store: JobStore | None = None,
        salary: str | None = None,
        experience: str | None = None,
        degree: str | None = None,
        industry: str | None = None,
        log=print,
    ) -> None:
        self.browser = browser
        self.query = query
        self.city_code = config.CITY_CODES.get(city, city)
        self.pages = max(1, pages)
        self.page_size = page_size
        self.with_detail = with_detail
        self.take = take
        self.store = store
        self.log = log
        # 界面筛选条件 -> 接口码
        self.filters = resolve_filters(
            salary=salary, experience=experience, degree=degree, industry=industry
        )
        self.jobs: list[dict] = []
        self._ready_page = None

    # ------------------------------------------------------------------ urls
    def _search_page_url(self) -> str:
        url = config.SEARCH_PAGE_URL.format(query=self.query, city=self.city_code)
        return f"{url}&{urlencode(self.filters)}" if self.filters else url

    def _list_api_url(self, page_no: int) -> str:
        url = config.JOB_LIST_API.format(
            query=self.query, city=self.city_code, page=page_no, page_size=self.page_size
        )
        return f"{url}&{urlencode(self.filters)}" if self.filters else url

    # ------------------------------------------------------------------ helpers
    def _warmup(self, page, *, seconds: float = 3.0) -> None:
        """打开真实的搜索页，让站点自己的 JS 走完安全检查、签发 __zp_stoken__。"""
        self.browser.goto(page, self._search_page_url())
        self.browser.ensure_armed(page)
        time.sleep(seconds + random.uniform(0.0, 2.0))
        try:
            page.mouse.wheel(0, random.randint(200, 700))
        except Exception:
            pass
        self._ready_page = page

    def _ready(self, page) -> None:
        """页面被重建后重新预热；SPA 硬跳转丢了注入就补回来。"""
        if self._ready_page is not page:
            self._warmup(page)
            return
        self.browser.ensure_armed(page)

    def _eval(self, page, js: str, arg=None):
        try:
            return page.evaluate(js, arg) if arg is not None else page.evaluate(js)
        except Exception as exc:  # 会话页面销毁的典型错误
            if any(marker in str(exc) for marker in _DESTROY_MARKERS):
                raise PageDestroyed(str(exc)) from exc
            raise

    def _fetch_json(self, page, url: str, *, purpose: str) -> dict:
        for _ in range(config.MAX_RISK_RETRIES + 1):
            page = self.browser.page()
            self._ready(page)
            try:
                result = self._eval(page, FETCH_JS, url)
            except PageDestroyed:
                self.log(f"  ! 页面被销毁（{purpose}），重建后重试")
                self._ready_page = None
                continue
            except Exception as exc:
                self.log(f"  ! 请求异常（{purpose}）：{exc}")
                self._ready_page = None
                continue

            payload = result.get("json")
            if payload is None:
                self.log(
                    f"  ! 非 JSON 响应（{purpose}）status={result.get('status')} "
                    f"{str(result.get('text', result.get('error', '')))[:80]!r}"
                )
                return {}

            code = payload.get("code")
            if code == 0:
                return payload

            message = payload.get("message") or ""
            if code == 37:
                self.log(f"  ! 风控命中 code=37（{purpose}）：{message}，退避后重新预热")
                human_sleep(config.RISK_BACKOFF)
                self._ready_page = None
                continue
            if code == 7 or "登录" in message:
                raise LoginRequired(f"登录态失效：code={code} {message}")
            self.log(f"  ! 接口返回 code={code} {message}（{purpose}）")
            return {}
        raise RuntimeError(f"{purpose} 连续触发风控，已停止")

    # ------------------------------------------------------------------ main
    def run(self) -> list[dict]:
        page = self.browser.page(goto=config.HOME_URL)
        if self.filters:
            self.log(f"筛选条件：{describe(self.filters)}")
        self._warmup(page, seconds=2.0)

        for page_no in range(1, self.pages + 1):
            list_url = self._list_api_url(page_no)
            self.log(f"[列表] 第 {page_no}/{self.pages} 页 …")
            payload = self._fetch_json(page, list_url, purpose=f"列表第{page_no}页")
            jobs, meta = parse_joblist(payload)

            if not jobs:
                try:
                    html = self._eval(self.browser.page(), DOM_JS)
                    jobs = parse_joblist_dom(html)
                    if jobs:
                        self.log(f"  ~ 接口为空，DOM 兜底解析到 {len(jobs)} 条")
                except Exception:
                    jobs = []

            self.log(f"  拿到 {len(jobs)} 条（total={meta.get('total')}）")
            for job in jobs:
                if self.store is not None and self.store.upsert(job):
                    self.jobs.append(job)
                elif self.store is None:
                    self.jobs.append(job)
                if self.take and len(self.jobs) >= self.take:
                    break

            if self.take and len(self.jobs) >= self.take:
                break
            if not meta.get("has_more"):
                break
            if page_no < self.pages:
                human_sleep(config.PAGE_DELAY)

        if self.with_detail:
            self._enrich_details()

        if self.store is not None:
            self.store.flush()
        return self.jobs

    def _enrich_details(self) -> None:        # 详情以 store 里的全量记录为准（DOM 兜底条目也有 url）
        records = self.store.records() if self.store is not None else self.jobs
        total = len(records)
        for index, job in enumerate(records, start=1):
            security_id = job.get("security_id")
            if not security_id:
                continue
            lid = job.get("lid") or ""
            url = config.JOB_DETAIL_API.format(security_id=security_id, lid=lid)
            self.log(f"[详情] {index}/{total} {job.get('title')} @ {job.get('company')}")
            payload = self._fetch_json(self.browser.page(), url, purpose=f"详情{index}")
            if payload:
                detail = parse_detail(payload)
                job.update({k: v for k, v in detail.items() if v})
                if self.store is not None:
                    self.store.upsert(job)
            human_sleep(config.DETAIL_DELAY)

    def enrich_records(
        self, records: list[dict], *, on_record=None, delay: tuple[float, float] | None = None
    ) -> list[dict]:
        """给已有记录回源补详情（主要补 address / description）。

        用于「先批量抓列表、再挑需要的补地址」的场景：只对传入的记录发请求。
        on_record(record, ok) 每处理完一条就回调一次，便于调用方逐条落盘（断点续跑）。
        """
        if not records:
            return records
        page = self.browser.page(goto=config.HOME_URL)
        self._warmup(page, seconds=2.0)
        total = len(records)
        for index, record in enumerate(records, start=1):
            security_id = record.get("security_id")
            if not security_id:
                continue
            url = config.JOB_DETAIL_API.format(
                security_id=security_id, lid=record.get("lid") or ""
            )
            self.log(f"[补详情] {index}/{total} {record.get('title')} @ {record.get('company')}")
            payload = self._fetch_json(
                self.browser.page(), url, purpose=f"补详情{index}"
            )
            ok = bool(payload)
            if payload:
                record.update({k: v for k, v in parse_detail(payload).items() if v})
            if on_record is not None:
                try:
                    on_record(record, ok)
                except Exception as exc:  # 落盘失败不应打断抓取
                    self.log(f"  ! 回调失败：{exc}")
            human_sleep(delay if delay is not None else config.DETAIL_DELAY)
        return records

