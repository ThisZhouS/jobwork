"""天眼查网页端工具（**不调用付费开放接口**）。

三个工具，各自只做一件事：

* ``tianyancha_search``  —— 按公司名搜出候选主体（含 id），用于实体锚定；
* ``tianyancha_company`` —— 取某主体的工商档案 + 侧栏计数；
* ``tianyancha_risk``    —— 尽力抓法律诉讼/经营风险子页（明细多为异步加载）。

反爬事实（实测 2026-10）：

* 带正常浏览器 UA/Accept 时搜索页返回 200、500KB+、几十个 ``/company/`` 链接；
* 但**连续几次后会退化成约 22KB 的登录墙外壳**（零个公司链接、连查询词都没有）。
  这种情况必须报 BLOCKED 而不是"没查到"，否则会误导判断；
* 关系与风险**明细不在 HTML 里**（走 XHR），所以只承诺"档案 + 计数"。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from ...base import AgentStatus
from ....providers.dd import name_score
from ....providers.relations import parse_profile
from ..base import Tool, ToolBox, ToolResult, register_tool
from ..parsing import clip, regex_field, strip_tags

_SEARCH_URL = "https://www.tianyancha.com/search?key={query}"
_COMPANY_URL = "https://www.tianyancha.com/company/{id}"
_SUBPAGE_URL = "https://www.tianyancha.com/company/{id}/{path}"

# 网页里能直接抠到的标量字段（键名与开放平台一致，便于复用 parse_profile）
PROFILE_KEYS = (
    "creditCode", "regStatus", "legalPersonName", "regCapital", "estiblishTime",
    "regLocation", "industry", "businessScope", "phoneNumber", "email", "website",
    "staffNum", "companyOrgType",
)

# 侧栏计数：这些数字免费可得，且对评分价值高
COUNT_LABELS = (
    "对外投资", "控制企业", "分支机构", "法律诉讼", "经营风险", "经营异常",
    "行政处罚", "股权出质", "动产抵押", "欠税", "招聘信息", "商标信息",
)
_COUNT_RE = re.compile(
    r"(?P<label>" + "|".join(COUNT_LABELS) + r")\s*(?P<num>\d{1,6}|999\+)")

_COMPANY_HREF_RE = re.compile(
    r'<a[^>]+href="(?:https?://www\.tianyancha\.com)?/company/(?P<id>\d+)"[^>]*>(?P<body>.*?)</a>',
    re.S | re.I,
)

_MIN_HTML = 800


class TianyanchaSearchTool(Tool):
    name = "tianyancha_search"
    site = "天眼查"
    description = "按公司名搜天眼查，返回候选主体（id/名称/链接），用于实体锚定"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", **_: Any) -> ToolResult:
        url = _SEARCH_URL.format(query=quote(company))
        outcome = await box.fetch_page(url, min_len=_MIN_HTML, wait_selector=None)
        if outcome.blocked:
            return ToolResult.blocked(
                self.name, "天眼查返回了登录墙/限频页面",
                notes=["降低频率（间隔 10s 以上）后重试，或用 --state 传登录态",
                       "免费且稳定的替代：tyc login 后用 tianyan_ai"],
                url=url,
            )
        if outcome.status is AgentStatus.FAILED:
            return ToolResult.failed(self.name, outcome.error or "搜索页抓取失败", url=url)

        rows = parse_company_list(outcome.html)
        if not rows:
            # 页面里连查询词都不出现 -> 是壳页，不是"真的没有"
            if company not in outcome.html:
                return ToolResult.blocked(
                    self.name, "天眼查返回的页面里没有查询词（疑似壳页）",
                    notes=["降低频率后重试，或改用 tianyan_ai"], url=url)
            return ToolResult.empty(self.name, url=url,
                                    notes=["搜索页没有解析到公司条目"])
        return ToolResult.ok_(self.name, rows, url=url)


class TianyanchaCompanyTool(Tool):
    name = "tianyancha_company"
    site = "天眼查"
    description = "取天眼查工商档案与规模/风险计数（免登录、免费）"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", company_id: str = "",
                   **_: Any) -> ToolResult:
        notes: list[str] = []
        if not company_id:
            found = await TianyanchaSearchTool().execute(box, company=company)
            if not found.usable or not found.data:
                return ToolResult(tool=self.name, status=found.status, error=found.error,
                                  notes=found.notes, url=found.url)
            candidates = found.data
            # 信站点自己的相关度排序：搜"茶百道"时首条就是正确主体，
            # 而纯字符串打分反而会选中"茶百道总店"这类更短的条目。
            best = candidates[0]
            score = name_score(company, best["name"])
            company_id = best["id"]
            if len(candidates) > 1:
                notes.append(f"站点返回 {len(candidates)} 个候选，取首条：{best['name']}")
                notes.append("其他候选：" + "、".join(c["name"] for c in candidates[1:4]))
            if score < 0.85:
                notes.append(f"名称匹配分偏低（{score:.2f}），请人工确认是否同一家")
        else:
            score = 1.0

        url = _COMPANY_URL.format(id=company_id)
        outcome = await box.fetch_page(url, min_len=_MIN_HTML)
        if outcome.blocked:
            return ToolResult.blocked(self.name, "详情页被拦", notes=notes, url=url)
        if outcome.status is AgentStatus.FAILED:
            return ToolResult.failed(self.name, outcome.error or "详情页抓取失败",
                                     notes=notes, url=url)

        profile = parse_profile(build_result_dict(outcome.html, company_id=company_id,
                                                 fallback_name=company))
        counts = parse_counts(outcome.html)
        if not profile.get("credit_code") and not profile.get("reg_status"):
            notes.append("未取到信用代码/登记状态，页面结构可能已变（建议 --dump-dir 后校准）")
        data = {
            "company_id": company_id,
            "url": url,
            "profile": profile,
            "counts": counts,
            "match_score": score,
        }
        status = AgentStatus.OK if profile else AgentStatus.PARTIAL
        return ToolResult(tool=self.name, status=status, data=data, notes=notes, url=url)


class TianyanchaRiskTool(Tool):
    name = "tianyancha_risk"
    site = "天眼查"
    description = "尽力抓法律诉讼/经营风险子页明细（多为异步加载，常只拿到计数）"
    params = ("company_id",)
    requires = ("http",)

    async def call(self, box: ToolBox, company_id: str = "", **_: Any) -> ToolResult:
        rows: list[dict] = []
        notes: list[str] = []
        partial = False
        for path, label in (("sifa", "法律诉讼"), ("jingxian", "经营风险")):
            url = _SUBPAGE_URL.format(id=company_id, path=path)
            outcome = await box.fetch_page(url, min_len=_MIN_HTML)
            if outcome.blocked or outcome.status is AgentStatus.FAILED:
                partial = True
                notes.append(f"{label}子页未取到（{outcome.error or '被拦截'}），明细需登录或用 tianyan_ai")
                continue
            found = parse_risk_rows(outcome.html, label)
            if not found:
                partial = True
                notes.append(f"{label}子页无明细行（异步加载），仅保留计数")
            rows.extend(found)
        if not rows:
            return ToolResult.partial(self.name, [], notes=notes)
        return ToolResult(tool=self.name,
                          status=AgentStatus.PARTIAL if partial else AgentStatus.OK,
                          data=rows, notes=notes)


class TianyanchaFullTool(Tool):
    """一次拿全：搜索锚定 → 详情页档案+计数 →（可选）风险子页。

    工具之间允许组合：这里串起另外三个工具，让 agent 只声明一次调用，
    而"怎么取"仍然全部留在工具层。
    """

    name = "tianyancha_full"
    site = "天眼查"
    description = "天眼查一站式：锚定主体 + 工商档案 + 规模/风险计数（可选风险子页）"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", include_risk: bool = True,
                   company_id: str = "", **_: Any) -> ToolResult:
        company_tool = TianyanchaCompanyTool()
        company_result = await company_tool.execute(box, company=company, company_id=company_id)
        if not company_result.usable or not company_result.data:
            return ToolResult(tool=self.name, status=company_result.status,
                              error=company_result.error, notes=company_result.notes,
                              url=company_result.url)

        data: dict[str, Any] = dict(company_result.data)
        notes = list(company_result.notes)
        status = company_result.status
        if include_risk and data.get("company_id"):
            risk = await TianyanchaRiskTool().execute(box, company_id=data["company_id"])
            notes.extend(risk.notes)
            if risk.usable:
                data["risks"] = risk.data or []
                if risk.status is AgentStatus.PARTIAL:
                    status = AgentStatus.PARTIAL
        return ToolResult(tool=self.name, status=status, data=data, notes=notes,
                          url=data.get("url"))


# ---------------------------------------------------------------- 解析
def parse_company_list(html: str) -> list[dict[str, Any]]:
    """从搜索页抽候选公司：``/company/{id}`` 链接 + 链接文字。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _COMPANY_HREF_RE.finditer(html or ""):
        company_id = match.group("id")
        name = strip_tags(match.group("body"))
        if not name or company_id in seen or len(name) < 4:
            continue
        seen.add(company_id)
        out.append({
            "id": company_id,
            "name": name,
            "url": _COMPANY_URL.format(id=company_id),
        })
    return out


def build_result_dict(html: str, *, company_id: str, fallback_name: str) -> dict[str, Any]:
    """把网页 HTML 拼成「开放平台 result」的形状，好让 parse_profile 直接复用。"""
    result: dict[str, Any] = {"id": company_id, "name": fallback_name}
    for key in PROFILE_KEYS:
        value = regex_field(html, key)
        if value:
            result[key] = value
    official = regex_field(html, "name")
    if official and len(official) >= 4:
        result["name"] = official
    return result


def parse_counts(html: str) -> dict[str, int]:
    """抽侧栏计数，如「对外投资10」「控制企业44」「法律诉讼1」。"""
    counts: dict[str, int] = {}
    for match in _COUNT_RE.finditer(html or ""):
        label = match.group("label")
        raw = match.group("num")
        value = 999 if raw == "999+" else int(raw)
        if value > counts.get(label, -1):
            counts[label] = value
    return counts


def parse_risk_rows(html: str, label: str) -> list[dict[str, Any]]:
    """子页明细行。结构化程度低，用日期做弱锚点，取不到就算了。"""
    rows: list[dict[str, Any]] = []
    text = strip_tags(html or "")
    for match in re.finditer(r"(20\d{2}-\d{2}-\d{2})[^\n]{0,80}", text):
        line = match.group(0).strip()
        if len(line) < 12:
            continue
        rows.append({
            "risk_type": "lawsuit" if label == "法律诉讼" else "abnormal",
            "occurred_at": match.group(1),
            "reason": clip(line, 160),
        })
        if len(rows) >= 20:
            break
    return rows


register_tool(TianyanchaSearchTool())
register_tool(TianyanchaCompanyTool())
register_tool(TianyanchaRiskTool())
register_tool(TianyanchaFullTool())
