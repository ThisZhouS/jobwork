"""巨潮资讯（cninfo）公告工具 —— 天眼查「风险提示」的免费平替。

为什么选它（调研结论）：

* ``POST /new/hisAnnouncement/query`` **不需要鉴权**，也不走滑块/验证码；
* 返回结构化 JSON（证券代码、公司名、标题、日期、PDF 链接），解析成本低；
* 上市公司被处罚、被立案、涉诉、业绩预警这些风险几乎都会发公告，
  所以「有没有风险公告」本身就是一个可用的风险信号。

边界（必须说清楚，否则会误用）：

* **只覆盖上市公司**。查非上市企业会返回空——这时候要标 ``unknown``
  （信息不足），绝不能标成「无风险」；
* 公告标题只能定「类型」，金额/案号要读 PDF 正文，这一步不在工具里做；
* 节流单域名 ≤0.2 QPS，由 ``HttpFetcher`` 的 delay 保证（默认 2s）。

接口与字段参考：http://www.cninfo.com.cn/new/hisAnnouncement/query
"""
from __future__ import annotations

from typing import Any

from ....agents.base import AgentStatus
from ..base import Tool, ToolBox, ToolResult, register_tool
from ..parsing import normalize_date, strip_tags

_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
_NOTICE_URL = "http://static.cninfo.com.cn/{path}"

#: 标题关键词 -> 风险类型。顺序有意义：先匹配到的先用（越靠前越严重）
RISK_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("立案调查", ("立案", "调查通知书", "行政处罚", "市场禁入")),
    ("重大诉讼", ("诉讼", "仲裁", "判决", "裁定", "起诉", "应诉")),
    ("失信被执行", ("失信", "被执行", "限制消费")),
    ("经营异常", ("经营异常", "异常名录", "责令改正")),
    ("股权风险", ("冻结", "质押", "司法拍卖", "轮候")),
    ("业绩预警", ("预亏", "亏损", "业绩预减", "退市风险", "终止上市", "停牌")),
    ("监管问询", ("问询函", "关注函", "监管函", "警示函", "通报批评")),
    ("高管变动", ("辞职", "离任", "罢免", "无法履职")),
    ("风险提示", ("风险提示", "澄清", "辟谣")),
)


def classify_risk(title: str) -> str:
    """按标题判定风险类型；没命中就返回 ``其他公告``。"""
    text = str(title or "")
    for label, words in RISK_KEYWORDS:
        if any(word in text for word in words):
            return label
    return "其他公告"


def is_risk(title: str) -> bool:
    """只有命中关键词才算风险公告，``其他公告``（分红、章程等）不算。"""
    return classify_risk(title) != "其他公告"


def to_date(stamp: Any) -> str | None:
    """公告时间可能是毫秒时间戳（数字或纯数字串），也可能是日期文本。"""
    if stamp is None:
        return None
    text = str(stamp).strip()
    if not text:
        return None
    # 13 位毫秒时间戳
    if text.isdigit() and len(text) >= 12:
        try:
            from datetime import datetime

            return datetime.fromtimestamp(int(text) / 1000).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None
    return normalize_date(text)


class CninfoNoticesTool(Tool):
    name = "cninfo_notices"
    site = "巨潮资讯"
    description = "查上市公司公告（处罚/立案/诉讼/风险提示），免鉴权，仅覆盖上市公司"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", limit: int = 30,
                   **_: Any) -> ToolResult:
        name = str(company or "").strip()
        if not name:
            return ToolResult.failed(self.name, "缺少公司名")

        http = await box.http()
        want = max(10, min(int(limit or 30), 50))
        headers = {
            "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }

        # 接口单页最多 30 条，要更多就得翻页
        raw: list[Any] = []
        page = 1
        while len(raw) < want and page <= 4:
            payload = {
                "pageNum": str(page),
                "pageSize": "30",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
                "searchkey": name,
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            try:
                data = await http.post_json(_QUERY_URL, data=payload, headers=headers)
            except Exception as exc:  # noqa: BLE001 - 网络问题统一降级
                if raw:
                    break     # 已经拿到部分就先用着
                return ToolResult.failed(self.name, f"请求公告接口失败：{exc}")

            if not isinstance(data, dict):
                return ToolResult.failed(self.name, "公告接口返回了非 JSON 对象")
            batch = data.get("announcements") or []
            if not batch:
                break
            raw.extend(batch)
            if len(batch) < 30:
                break
            page += 1
        raw = raw[:want]
        if not raw:
            # 查不到有两种可能：公司没发过公告（非上市），或名字没匹配上。
            # 这两种都不能当"无风险"，所以返回 EMPTY 并写明原因。
            return ToolResult.empty(
                self.name,
                notes=[f"巨潮资讯未检索到「{name}」的公告（非上市公司的正常结果）"],
                url=_QUERY_URL)

        rows: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            # 接口开了 isHLtitle，标题里会带 <em> 高亮标签，去掉
            title = strip_tags(str(item.get("announcementTitle") or "")).strip()
            if not title:
                continue
            adjunct = str(item.get("adjunctUrl") or "").strip()
            stamp = item.get("announcementTime")
            date = to_date(stamp)
            rows.append({
                "title": title,
                "date": date,
                "published_at": date,      # rows_to_findings 认这个键
                "risk_type": classify_risk(title),
                "is_risk": is_risk(title),
                "sec_name": str(item.get("secName") or "").strip(),
                "sec_code": str(item.get("secCode") or "").strip(),
                "url": _NOTICE_URL.format(path=adjunct) if adjunct else None,
            })

        risky = [row for row in rows if row["is_risk"]]
        notes = [f"共 {len(rows)} 条公告，其中风险类 {len(risky)} 条"]
        if not risky:
            notes.append("没有风险类公告：这不等于无风险，只说明没有相关披露")

        status = AgentStatus.OK if risky else AgentStatus.PARTIAL
        return ToolResult(tool=self.name, status=status, data=rows,
                          notes=notes, url=_QUERY_URL,
                          meta={"total": len(rows), "risky": len(risky)})


register_tool(CninfoNoticesTool)


__all__ = ["CninfoNoticesTool", "RISK_KEYWORDS", "classify_risk", "is_risk"]
