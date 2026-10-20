"""天眼查 spider：把背调流程表达成「请求链路」。

挂在通用引擎上，于是自动获得队列、并发、去重、重试、统计，而业务逻辑
仍然只有「哪一步产出哪些请求」。

链路（每家一行公司）::

    parse_search ──> parse_ic ──┬─> parse_risk(自身失信/被执行)
        (名称->实体)   (工商全景)  ├─> parse_risk(母公司 失信/被执行)
                                   └─> parse_risk(控股子公司 失信/被执行)

每一步产出 ``Item``（交给管道落库）或下一个 ``Request``（回到队列）。
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from .. import config
from ..engine import Item, Request, Response, Spider
from . import relations as rel
from .tianyancha import NON_RETRYABLE, TianyanchaError, load_token

# 这些业务错误码重试没有意义（token 错、余额不足等），其余业务错误默认重试
_NON_RETRYABLE = frozenset(NON_RETRYABLE)


class TianyanchaSpider(Spider):
    """按公司名单做背调。

    参数
    ----
    companies:
        ``[{"company_key": ..., "company_name": ..., "legal_name": ...}]``
    """

    name = "tianyancha"

    custom_settings = {
        "CONCURRENT_REQUESTS": 4,
        "DOWNLOAD_DELAY": 0.35,
        "ERROR_CODE_FIELD": "error_code",
        "ERROR_REASON_FIELD": "reason",
        "RETRY_TIMES": 3,
        "DROP_FAILED": True,
    }

    def __init__(
        self,
        companies: list[dict],
        *,
        token: str | None = None,
        min_percent: float = 20.0,
        max_related: int = 3,
        skip_risks: bool = False,
        only_relations: bool = False,
        max_cost: float = 30.0,
        resolution_threshold: float = 0.85,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.companies = list(companies)
        self.token = (token if token is not None else load_token()).strip()
        self.min_percent = min_percent
        self.max_related = max_related
        self.skip_risks = skip_risks
        self.only_relations = only_relations
        self.max_cost = max_cost
        self.resolution_threshold = resolution_threshold
        self.spent = 0.0
        self.cost_by_api: dict[str, float] = {}

    # ---------------------------------------------------------------- 基础
    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": self.token,
            "Accept": "application/json",
            "User-Agent": "boss-crawler/0.3 (+personal research)",
        }

    def _request(self, api: str, params: dict, meta: dict, *, callback: str, priority: int = 0) -> Request:
        return Request(
            url=f"{config.TYC_BASE_URL}{config.TYC_API[api]}",
            params=params,
            meta={**meta, "api": api},
            headers=self.headers,
            callback=callback,
            priority=priority,
        )

    def _charge(self, api: str) -> None:
        """记录花费。并发下是近似值，用于预算兜底。"""
        price = config.TYC_PRICES.get(api, 0.0)
        self.spent += price
        self.cost_by_api[api] = self.cost_by_api.get(api, 0.0) + price

    def _over_budget(self) -> bool:
        return self.max_cost > 0 and self.spent >= self.max_cost

    # ---------------------------------------------------------------- 入口
    async def start_requests(self) -> AsyncIterator[Request]:
        if not self.token:
            raise TianyanchaError("缺少天眼查 token：请在 .env 写 TIANYANCHA_TOKEN=...")
        for company in self.companies:
            query = company.get("legal_name") or company.get("company_name") or ""
            yield self._request(
                "search",
                {"word": query, "pageSize": 5, "pageNum": 1},
                {
                    "company_key": company["company_key"],
                    "company_name": company.get("company_name") or "",
                    "query": query,
                    "stage": "search",
                },
                callback="parse_search",
                priority=10,
            )

    # ---------------------------------------------------------------- 步骤 1
    async def parse_search(self, response: Response) -> AsyncIterator[Any]:
        """名称 -> 天眼查实体。命中就推进到工商全景。"""
        meta = dict(response.meta)
        items = ((response.payload or {}).get("result") or {}).get("items") or []
        self._charge("search")

        best, score = _pick_best(meta["query"], items)
        if best is None:
            yield Item(
                "company_skipped",
                company_key=meta["company_key"],
                company_name=meta["company_name"],
                note="天眼查无匹配（可能是脱敏名/已注销）",
            )
            return

        note = None
        if score < self.resolution_threshold:
            note = f"名称匹配分偏低（{score}），需人工确认"

        keyword = best.get("creditCode") or best.get("id") or meta["query"]
        yield self._request(
            "ic",
            {"keyword": keyword},
            {
                **meta,
                "stage": "ic",
                "tyc_id": best.get("id"),
                "tyc_name": best.get("name"),
                "credit_code": best.get("creditCode"),
                "match_score": score,
                "match_note": note,
                "keyword": keyword,
            },
            callback="parse_ic",
            priority=9,
        )

    # ---------------------------------------------------------------- 步骤 2
    async def parse_ic(self, response: Response) -> AsyncIterator[Any]:
        """工商全景：一次拿到档案、母子关系、以及三类自带风险。"""
        meta = dict(response.meta)
        result = (response.payload or {}).get("result") or {}
        self._charge("ic")
        if not result:
            yield Item(
                "company_skipped",
                company_key=meta["company_key"],
                company_name=meta["company_name"],
                note="工商全景返回为空",
            )
            return

        key = meta["company_key"]
        profile = rel.parse_profile(result)

        yield Item(
            "company_profile",
            company_key=key,
            company_name=meta["company_name"],
            profile=profile,
            match_score=meta.get("match_score"),
            match_note=meta.get("match_note"),
            raw=result,
        )

        # ---- 关系边：母公司 / 控股子公司 / 分支
        rows = rel.parse_relations(result, from_key=key)
        subs = [r for r in rows if r["relation"] == "subsidiary" and (r.get("percent") or 0) >= self.min_percent]
        kept = [r for r in rows if r["relation"] != "subsidiary"] + subs
        yield Item("company_relations", company_key=key, rows=kept)

        # ---- 自身三类自带风险（不再额外花钱）
        risk_rows = rel.parse_risks(
            result,
            entity_key=str(profile.get("tyc_id") or meta.get("keyword")),
            entity_name=profile.get("name") or meta["company_name"],
        )
        for row in risk_rows:
            row["relation"] = "self"

        # 先声明「这家公司要落风险」，即使后续全部失败也会清掉旧数据
        yield Item("company_risk_watch", related_key=key)
        if risk_rows:
            yield Item("company_risk", related_key=key, rows=risk_rows)

        if self.skip_risks:
            return

        # ---- 自身失信 + 被执行
        keyword = meta.get("keyword")
        entity_key = str(profile.get("tyc_id") or keyword)
        entity_name = profile.get("name") or meta["company_name"]
        for api in ("dishonest", "zhixing"):
            yield self._risk_request(
                api, keyword, meta,
                related_key=key, relation="self",
                entity_key=entity_key, entity_name=entity_name,
            )

        # ---- 关联方风险（母公司 + 控股子公司，受 max_related / 预算约束）
        if self.only_relations:
            return
        related = [r for r in kept if r["relation"] in ("parent", "subsidiary")][: self.max_related]
        for row in related:
            if self._over_budget():
                break
            side = "parent" if row["relation"] == "parent" else "subsidiary"
            sub_key = f"tyc:{row.get('to_tyc_id') or row['to_name']}"
            target = row.get("to_tyc_id") or row["to_name"]
            for api in ("dishonest", "zhixing"):
                yield self._risk_request(
                    api, target, meta,
                    related_key=key, relation=side,
                    entity_key=sub_key, entity_name=row["to_name"],
                )

    # ---------------------------------------------------------------- 步骤 3
    def _risk_request(self, api: str, keyword: Any, meta: dict, *, related_key: str,
                      relation: str, entity_key: str, entity_name: str) -> Request:
        return self._request(
            api,
            {"keyword": keyword, "pageNum": 1, "pageSize": 20},
            {
                **meta,
                "stage": "risk",
                "related_key": related_key,
                "relation": relation,
                "entity_key": entity_key,
                "entity_name": entity_name,
                # 同一家公司对同一个实体只查一次，避免重复计费
                "fingerprint_extra": f"{api}:{entity_key}",
            },
            callback="parse_risk",
            priority=5,
        )

    async def parse_risk(self, response: Response) -> AsyncIterator[Any]:
        """失信人 / 被执行人。"""
        meta = dict(response.meta)
        api = meta["api"]
        result = (response.payload or {}).get("result") or {}
        self._charge(api)

        parser = rel.parse_dishonest if api == "dishonest" else rel.parse_zhixing
        rows = parser(result, entity_key=meta["entity_key"], entity_name=meta["entity_name"])
        for row in rows:
            row["relation"] = meta["relation"]
        if rows:
            yield Item("company_risk", related_key=meta["related_key"], rows=rows)

    # ---------------------------------------------------------------- 策略
    def should_retry(self, response: Response, attempt: int) -> bool | None:
        """业务错误码判定：鉴权/余额类不重试，其余非零码重试。"""
        if response.error is not None:
            return True
        if response.error_code is None:
            return None            # 传输层成功且无业务码 -> 交给引擎默认策略
        if response.error_code == 0:
            return False
        return response.error_code not in _NON_RETRYABLE


def _pick_best(query: str, items: list[dict]) -> tuple[dict | None, float]:
    """代理到 ``dd.pick_best``，避免两处打分逻辑漂移。"""
    from .dd import pick_best

    return pick_best(query, items)
