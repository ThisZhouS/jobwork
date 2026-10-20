"""背调编排：从库里取公司名 → 天眼查查档案与关联方 → 落库。

流程（每一步都写 ``tyc_fetch_log``，可核对花了多少钱）::

    库里 companies（跳过脱敏）
      → 816 搜索：名称 → 天眼查实体（creditCode / id），并打分
      → 1001 工商全景：档案 + 主要人员/股东/对外投资/分支 + 自身风险清单
      → 963 总公司（1001 没给 headquaters 时兜底）
      → 843 失信人 + 839 被执行人：自身
      → 对母公司、控股子公司重复上述风险查询（``depth``/``max_related`` 控制预算）

预算控制：:class:`DueDiligenceOptions` 里的 ``max_related`` 与 ``depth`` 决定
关联方查到第几层、每层查几家，配合 ``client.spent`` 可随时叫停。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import relations as rel
from .tianyancha import TianyanchaClient, TianyanchaError

# 1001 里已自带这三类风险清单，不必再单买
_RISK_IN_IC = ("abnormal", "illegal", "punish")


@dataclass
class DueDiligenceOptions:
    """背调预算与范围。

    * ``depth``：往上/往下查几层（1 = 只查直接母公司与直接对外投资）；
    * ``max_related``：每个主体最多查几家关联方的风险（越小越省钱）；
    * ``min_percent``：对外投资里，持股比例低于该值的不当作子公司；
    * ``only_relations``：只抓关系，不查关联方风险（最省）；
    * ``max_cost``：累计花费上限（元），超过即停止。
    """

    depth: int = 1
    max_related: int = 3
    min_percent: float = 20.0
    only_relations: bool = False
    skip_risks: bool = False
    max_cost: float = 30.0
    resolution_threshold: float = 0.85


@dataclass
class DueDiligenceResult:
    """单个公司的背调结果摘要。"""

    company_key: str
    company_name: str
    matched: bool = False
    tyc_name: str = ""
    credit_code: str = ""
    score: float = 0.0
    relations: int = 0
    risks: int = 0
    cost: float = 0.0
    note: str = ""
    risk_types: dict[str, int] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        return rel.verdict(self.risk_types)


def name_score(query: str, candidate: str) -> float:
    """名称匹配分：完全相同 1.0；互相包含按重叠度给 0.75~1.0；否则按公共字符比例。

    BOSS 上的公司名大量是简称（``茶百道`` 对 ``四川茶百道实业股份有限公司``），
    所以不做严格相等。包含关系是强信号，起点给 0.75，再按字符重叠度加成；
    完全无关的名字靠公共字符比例，通常落在 0.2 以下。
    """
    q = (query or "").strip()
    c = (candidate or "").strip()
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        overlap = min(len(q), len(c)) / max(len(q), len(c))
        return round(0.75 + 0.25 * overlap, 3)
    common = len(set(q) & set(c))
    return round(common / max(len(set(q)), len(set(c))), 3)


def pick_best(query: str, items: Iterable[dict]) -> tuple[dict | None, float]:
    """在搜索结果里挑最像的一家。"""
    best: dict | None = None
    best_score = 0.0
    for item in items or []:
        score = name_score(query, item.get("name", ""))
        if score > best_score:
            best, best_score = item, score
    return best, best_score


def _risk_rows(client: TianyanchaClient, keyword: Any, *,
               entity_key: str, entity_name: str, relation: str,
               db_log: Callable[[dict], None] | None = None) -> list[dict]:
    """查一家实体的失信 + 被执行（两项最关键的判决类风险）。"""
    rows: list[dict] = []
    for api, parser in (("dishonest", rel.parse_dishonest), ("zhixing", rel.parse_zhixing)):
        try:
            result = client.get(api, {"keyword": keyword, "pageNum": 1, "pageSize": 20})
        except TianyanchaError as exc:
            if db_log:
                db_log({"api": api, "keyword": str(keyword), "code": exc.code, "price": 0.0})
            continue
        rows.extend(parser(result, entity_key=entity_key, entity_name=entity_name))
        if db_log:
            db_log(client.calls[-1])
    for row in rows:
        row["relation"] = relation
    return rows


def investigate(
    db: Any,
    targets: list[dict],
    *,
    options: DueDiligenceOptions | None = None,
    client: TianyanchaClient | None = None,
    on_progress: Callable[[DueDiligenceResult], None] | None = None,
) -> list[DueDiligenceResult]:
    """对一批公司做背调并写库。

    ``db`` 需要提供 ``save_tyc_profile`` / ``replace_tyc_relations`` /
    ``replace_tyc_risks`` / ``log_tyc_call`` 四个方法（见 :class:`Database`）。
    """
    opts = options or DueDiligenceOptions()
    client = client or TianyanchaClient()
    results: list[DueDiligenceResult] = []

    for target in targets:
        key = target["company_key"]
        name = target["company_name"]
        # 优先用工商全称去查，命中率高得多；没有再用 BOSS 上的名字
        query = target.get("legal_name") or name
        result = DueDiligenceResult(company_key=key, company_name=name)

        if client.spent >= opts.max_cost:
            result.note = f"已达预算上限 ¥{opts.max_cost}，跳过"
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        # ---- 1. 名称 -> 天眼查实体
        try:
            found = client.search(query, page_size=5)
            db.log_tyc_call(key, client.calls[-1])
        except TianyanchaError as exc:
            result.note = f"搜索失败：{exc}"
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        best, score = pick_best(query, found.get("items") or [])
        if not best:
            result.note = "天眼查无匹配（可能是脱敏名/已注销）"
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        result.matched = True
        result.tyc_name = best.get("name") or ""
        result.credit_code = best.get("creditCode") or ""
        result.score = score
        keyword = result.credit_code or best.get("id") or query
        if score < opts.resolution_threshold:
            result.note = f"名称匹配分偏低（{score}），需人工确认"

        # ---- 2. 工商全景
        try:
            ic = client.ic(keyword)
            db.log_tyc_call(key, client.calls[-1])
        except TianyanchaError as exc:
            result.note = (result.note + "；" if result.note else "") + f"工商查询失败：{exc}"
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        profile = rel.parse_profile(ic)
        db.save_tyc_profile(key, profile, match_score=score,
                            match_note=result.note or None, raw=ic)

        # ---- 3. 关系（母子 + 分支）
        rel_rows = rel.parse_relations(ic, from_key=key)
        if not any(r["relation"] == "parent" for r in rel_rows):
            try:
                parent = client.parent(keyword)
                if parent and parent.get("name"):
                    rel_rows.append(
                        {
                            "from_key": key,
                            "relation": "parent",
                            "to_tyc_id": parent.get("id"),
                            "to_name": parent.get("name"),
                            "to_reg_status": parent.get("reg_status"),
                            "percent": None,
                            "grade": "总公司",
                        }
                    )
            except TianyanchaError:
                pass

        # 只有控股及以上的对外投资才算子公司，避免把财务投资当关联方
        subs = [
            r for r in rel_rows
            if r["relation"] == "subsidiary" and (r.get("percent") or 0) >= opts.min_percent
        ]
        kept = [r for r in rel_rows if r["relation"] != "subsidiary"] + subs
        db.replace_tyc_relations(key, kept)
        result.relations = len(kept)

        # ---- 4. 自身风险：1001 自带三类，失信/被执行另行查
        risk_rows = rel.parse_risks(ic, entity_key=str(profile.get("tyc_id") or keyword),
                                    entity_name=profile.get("name") or name)
        for row in risk_rows:
            row["relation"] = "self"

        if not opts.skip_risks:
            risk_rows += _risk_rows(
                client, keyword,
                entity_key=str(profile.get("tyc_id") or keyword),
                entity_name=profile.get("name") or name,
                relation="self",
                db_log=lambda call: db.log_tyc_call(key, call),
            )

        # ---- 5. 母公司 / 控股子公司的风险（这才是「关联方风险」）
        if not opts.skip_risks and not opts.only_relations and opts.depth >= 1:
            related = [r for r in kept if r["relation"] in ("parent", "subsidiary")][: opts.max_related]
            for item in related:
                if client.spent >= opts.max_cost:
                    break
                side = "parent" if item["relation"] == "parent" else "subsidiary"
                sub_key = f"tyc:{item.get('to_tyc_id') or item['to_name']}"
                rows = _risk_rows(
                    client, item.get("to_tyc_id") or item["to_name"],
                    entity_key=sub_key, entity_name=item["to_name"], relation=side,
                    db_log=lambda call: db.log_tyc_call(key, call),
                )
                risk_rows.extend(rows)

        db.replace_tyc_risks(key, risk_rows)
        result.risks = len(risk_rows)
        result.risk_types = rel.risk_summary(risk_rows)
        result.cost = round(client.spent, 2)
        results.append(result)
        if on_progress:
            on_progress(result)

    return results


def print_summary(results: list[DueDiligenceResult], *, cost: float | None = None) -> None:
    """把结果打成一张可读的表。"""
    print(f"{'公司':32} {'匹配':4} {'关系':4} {'风险':4} {'结论'}")
    print("-" * 96)
    for item in results:
        flag = "✓" if item.matched else "×"
        name = item.company_name[:30]
        print(f"{name:32} {flag:4} {item.relations:<4} {item.risks:<4} {item.verdict}")
        if item.note:
            print(f"{'':32} └─ {item.note}")
    if cost is not None:
        print(f"\n本次花费约 ¥{cost:.2f}")


def estimate_cost(n: int, *, depth: int = 1, max_related: int = 3) -> dict[str, float]:
    """估算一批公司的调用成本（元），跑之前先看预算。

    每家固定：搜索 0.01 + 工商全景 1.00 + 失信 0.15 + 被执行 0.15。
    关联方只查失信 + 被执行（0.30/家），关系本身来自 1001，不额外收费。
    """
    from .. import config

    prices = config.TYC_PRICES
    per_company = prices["search"] + prices["ic"] + prices["dishonest"] + prices["zhixing"]
    per_related = prices["dishonest"] + prices["zhixing"]
    related = max_related * max(depth, 0)
    total = n * (per_company + related * per_related)
    return {
        "per_company": round(per_company, 2),
        "per_related": round(per_related, 2),
        "total": round(total, 2),
    }
