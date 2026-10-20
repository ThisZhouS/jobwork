"""agent 侧的总结层：调工具 → 汇总 → 出结果。

这一层刻意很薄。agent 不写反爬、不写解析，只声明"我要调哪些工具"，
剩下的（开工具箱、按顺序调用、把行变成 Finding、算情感分布、判定状态）
由 :class:`ToolAgent` 统一处理。

于是加一个 agent 只需：

```python
class MyAgent(ToolAgent):
    name = "my_agent"
    tools = (ToolCall("zhihu_search"),)
```

需要特殊总结逻辑时再覆盖 :meth:`ToolAgent.summarize`。
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .base import (
    Agent,
    AgentContext,
    AgentKind,
    AgentRequest,
    AgentResult,
    AgentStatus,
    Finding,
)
from .tools import ToolBox, ToolResult, Tool, get_tool
from .tools.parsing import clip, dedupe, make_finding, negative_ratio, sentiment_of


@dataclass
class ToolCall:
    """一次工具调用声明。"""

    tool: str
    #: 生成的 Finding.source；默认与工具同名
    source: str = ""
    #: 从 request 里取参数（默认只需 company）
    params: Callable[[AgentRequest], dict[str, Any]] = field(
        default=lambda request: {"company": request.require_company()})
    #: rows = 返回行列表 -> 变成 findings；data = 返回结构化数据 -> 放进 meta/metrics
    produces: str = "rows"

    def build_params(self, request: AgentRequest) -> dict[str, Any]:
        return self.params(request)

    @property
    def finding_source(self) -> str:
        return self.source or self.tool


@asynccontextmanager
async def open_toolbox(ctx: AgentContext):
    """开一个工具箱，用完关掉（只关自己创建的 http/browser）。"""
    box = ToolBox(ctx)
    try:
        yield box
    finally:
        await box.close()


class ToolAgent(Agent):
    """只负责"调工具 + 总结"的 agent 基类。

    另外两件事固定在基类里，子类不用管：

    * **诊断必挂**：每个 agent 都要能写"报错/缺失数据/失败原因"，
      所以 ``log_event`` 是强制工具，状态不对时自动落一条；
    * **原数据直存**：``produces="raw"`` 的调用（如天眼查）不总结，
      原样写进 ``backduty_raw``。
    """

    kind = AgentKind.BACKDUTY
    produces = ("findings",)
    #: 需要哪些外部条件，由子类声明（http / browser / cli）
    tools: tuple[ToolCall, ...] = ()

    #: 强制工具：不写进 ``tools``，但一定可用（要求"所有 agent 必须含报错日志写入"）
    mandatory_tools: tuple[str, ...] = ("log_event",)
    log_tool = "log_event"

    async def run(self, request: AgentRequest, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        results: list[ToolResult] = []
        async with open_toolbox(ctx) as box:
            for call in self.tools:
                tool: Tool = get_tool(call.tool)
                params = call.build_params(request)
                results.append(await tool.execute(box, **params))
            result = self.summarize(request, results, started)
            await self.persist(box, request, result, results)
            await self.diagnose(box, request, result)
        return result

    # ------------------------------------------------------------ 落库与诊断
    async def persist(self, box: ToolBox, request: AgentRequest,
                      result: AgentResult, results: list[ToolResult]) -> None:
        """把 ``produces="raw"`` 的产出原样存进 backduty_raw（不总结）。"""
        store = _store(box)
        if store is None:
            return
        company_key = _company_key(request)
        for call, tool_result in zip(self.tools, results):
            if call.produces != "raw" or not tool_result.usable or tool_result.data is None:
                continue
            try:
                store.save_raw(company_key, self.name, tool_result.data,
                               run_id=box.ctx.option("run_id"))
            except Exception as exc:  # noqa: BLE001 - 存原数据失败不该中断
                result.notes.append(f"{call.tool} 原数据存库失败：{type(exc).__name__}")

    async def diagnose(self, box: ToolBox, request: AgentRequest,
                       result: AgentResult) -> None:
        """状态不对时写一条诊断（报错日志/缺失数据工具）。"""
        status = result.status
        if status is AgentStatus.OK:
            return
        needs_reason = status in (AgentStatus.BLOCKED, AgentStatus.FAILED,
                                  AgentStatus.EMPTY, AgentStatus.PARTIAL)
        if not needs_reason:
            return
        level = {AgentStatus.BLOCKED: "warn", AgentStatus.FAILED: "error",
                 AgentStatus.EMPTY: "warn", AgentStatus.PARTIAL: "warn"}[status]
        message = result.error or "；".join(result.notes[:2]) or "没有取到数据"
        try:
            await get_tool(self.log_tool).execute(
                box,
                message=str(message),
                level=level,
                status=status.value,
                code=_reason_code(result),
                agent=self.name,
                tool=",".join(result.meta.get("tools") or []) or None,
                context={"company": getattr(request, "company_name", ""),
                         "tool_statuses": result.meta.get("tool_statuses")},
            )
        except Exception:  # noqa: BLE001 - 诊断本身永不影响主流程
            pass

    # ------------------------------------------------------------ 总结
    def summarize(self, request: AgentRequest, results: list[ToolResult],
                  started: float) -> AgentResult:
        findings: list[Finding] = []
        metrics: dict[str, Any] = {}
        notes: list[str] = []
        errors: list[str] = []

        for call, result in zip(self.tools, results):
            notes.extend(result.notes)
            if result.error and result.status in (AgentStatus.FAILED, AgentStatus.BLOCKED):
                errors.append(f"{call.tool}: {result.error}")
            if result.status not in (AgentStatus.OK, AgentStatus.PARTIAL):
                continue
            if call.produces == "rows":
                findings.extend(rows_to_findings(result.data or [], call.finding_source))
            elif call.produces == "raw":
                # 不总结：原样进 metrics，由 persist() 存进 backduty_raw
                metrics[call.tool] = result.data
            else:
                metrics[call.tool] = result.data
                findings.extend(self.findings_from_data(call, result))

        findings = dedupe(findings)
        has_data = any(r.usable and r.data for r in results)
        status = self.decide_status(results, findings, has_data)
        meta = {
            "tools": [result.tool for result in results],
            "tool_statuses": {result.tool: result.status.value for result in results},
            "elapsed_s": round(time.perf_counter() - started, 2),
        }
        meta.update(self.extra_meta(results))
        if metrics:
            meta["metrics"] = metrics

        return AgentResult(
            agent=self.name,
            status=status,
            findings=findings,
            notes=_shorten(notes),
            error="；".join(errors) if errors and status in (AgentStatus.FAILED, AgentStatus.BLOCKED) else None,
            elapsed_s=meta["elapsed_s"],
            meta=meta,
        )

    # ------------------------------------------------------------ 钩子
    def findings_from_data(self, call: ToolCall, result: ToolResult) -> list[Finding]:
        """结构化数据也可以变成一条"证据"（默认一条摘要 Finding）。"""
        data = result.data
        if not isinstance(data, dict):
            return []
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        title = str(
            data.get("matched_name")
            or data.get("company")
            or (profile or {}).get("name")
            or ""
        )
        snippet = describe_data(data)
        if not title and not snippet:
            return []
        return [make_finding(call.finding_source, title=title or "工具返回",
                             url=str(data.get("url") or ""), snippet=snippet,
                             payload=data)]

    def decide_status(self, results: list[ToolResult], findings: list[Finding],
                      has_data: bool | None = None) -> AgentStatus:
        """状态优先级：有数据 > EMPTY > BLOCKED > FAILED。

        ``has_data`` 用来覆盖"只存原数据、不产 Finding"的 agent（如天眼查）——
        它们没有 findings，但确实取到了东西。
        """
        statuses = [result.status for result in results]
        got_data = has_data if has_data is not None else bool(findings)
        if got_data or findings:
            if any(status is AgentStatus.PARTIAL for status in statuses):
                return AgentStatus.PARTIAL
            return AgentStatus.OK
        if any(status is AgentStatus.PARTIAL for status in statuses):
            return AgentStatus.PARTIAL
        if AgentStatus.EMPTY in statuses:
            return AgentStatus.EMPTY
        if AgentStatus.BLOCKED in statuses:
            return AgentStatus.BLOCKED
        if AgentStatus.FAILED in statuses:
            return AgentStatus.FAILED
        return AgentStatus.EMPTY

    def extra_meta(self, results: list[ToolResult]) -> dict[str, Any]:
        return {}


# ---------------------------------------------------------------- 转换


def rows_to_findings(rows: Iterable[Any], source: str) -> list[Finding]:
    """把工具返回的行变成 Finding（顺手算情感与日期）。"""
    out: list[Finding] = []
    for row in rows or []:
        if isinstance(row, Finding):
            out.append(row)
            continue
        if not isinstance(row, dict):
            continue
        extra = {k: v for k, v in row.items()
                 if k not in ("title", "url", "snippet", "published_at", "author")}
        out.append(make_finding(
            source,
            title=str(row.get("title") or ""),
            url=str(row.get("url") or ""),
            snippet=str(row.get("snippet") or ""),
            published_at=row.get("published_at"),
            author=row.get("author"),
            **extra,
        ))
    return out


def describe_data(data: dict[str, Any]) -> str:
    """把结构化数据压成一句人话，作为 Finding 的 snippet。"""
    parts: list[str] = []
    profile = data.get("profile")
    if isinstance(profile, dict) and profile:
        if profile.get("reg_status"):
            parts.append(f"登记状态：{profile['reg_status']}")
        if profile.get("reg_capital"):
            parts.append(f"注册资本：{profile['reg_capital']}")
        if profile.get("estiblish_time"):
            parts.append(f"成立：{profile['estiblish_time']}")
        if profile.get("reg_location"):
            parts.append(f"地址：{clip(str(profile['reg_location']), 60)}")
        if profile.get("business_scope"):
            parts.append("经营范围：" + clip(str(profile["business_scope"]), 100))
    counts = data.get("counts")
    if isinstance(counts, dict) and counts:
        parts.append("计数：" + "，".join(f"{k}{v}" for k, v in list(counts.items())[:6]))
    bundle = data.get("bundle")
    if isinstance(bundle, dict) and bundle:
        parts.append(clip(describe_bundle(bundle), 200))
    if not parts and data.get("company"):
        parts.append(f"实体：{data['company']}")
    return "；".join(parts)


def describe_bundle(bundle: dict[str, Any]) -> str:
    """天眼AI bundle 的摘要。"""
    parts: list[str] = []
    registration = _as_dict(bundle.get("registration"))
    if registration.get("regStatus"):
        parts.append(f"登记状态：{registration['regStatus']}")
    if registration.get("regCapital"):
        parts.append(f"注册资本：{registration['regCapital']}")
    scale = _as_dict(bundle.get("scale"))
    level = scale.get("scale") or scale.get("level")
    if level:
        parts.append(f"规模：{level}")
    ipr = _as_dict(bundle.get("ipr_score"))
    score = ipr.get("score") or ipr.get("totalScore")
    if score is not None:
        parts.append(f"创新力评分：{score}")
    risk = _as_dict(bundle.get("risk"))
    summary = risk.get("_summary") or risk.get("summary")
    if summary:
        parts.append(str(summary)[:160])
    else:
        counts = {k: v for k, v in risk.items() if isinstance(v, (int, float)) and v}
        if counts:
            parts.append("风险计数：" + "，".join(f"{k}{v}" for k, v in list(counts.items())[:5]))
    return "；".join(parts)


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        for key in ("data", "result"):
            inner = value.get(key)
            if isinstance(inner, dict):
                return inner
        return value
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return {}


def sentiment_summary(findings: Iterable[Finding]) -> dict[str, Any]:
    """情感分布摘要，供报告与评分使用。"""
    items = list(findings)
    judged = [f for f in items if f.sentiment is not None]
    positive = sum(1 for f in judged if f.sentiment > 0)
    negative = sum(1 for f in judged if f.sentiment < 0)
    top_negative = sorted(
        (f for f in judged if f.sentiment < 0),
        key=lambda f: f.weight, reverse=True,
    )[:3]
    return {
        "total": len(items),
        "judged": len(judged),
        "positive": positive,
        "negative": negative,
        "neutral": len(judged) - positive - negative,
        "negative_ratio": negative_ratio(items),
        "top_negative": [{"title": f.title, "url": f.url, "weight": f.weight}
                         for f in top_negative],
    }


def _shorten(notes: Iterable[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    for note in notes:
        text = str(note).strip()
        if text and text not in out:
            out.append(text)
    return out[:limit]


def _store(box: ToolBox):
    """拿应用层存储：优先注入的 store，其次从 ctx.db 现搭一个。"""
    store = box.ctx.option("store")
    if store is not None:
        return store
    if box.ctx.db is None:
        return None
    try:
        from ..store.app_store import AppStore

        return AppStore(box.ctx.db)
    except Exception:  # noqa: BLE001 - 没有存储也不该影响取证
        return None


def _company_key(request: AgentRequest) -> str:
    """落库用的公司主键：优先显式给的 key，否则用公司名。"""
    key = getattr(request, "company_key", None)
    if key:
        return str(key)
    return str(getattr(request, "company_name", "") or "")


def _reason_code(result: AgentResult) -> str:
    """把状态翻成机器可读的原因码，便于前端分类统计。"""
    statuses = set((result.meta.get("tool_statuses") or {}).values())
    if result.status is AgentStatus.BLOCKED:
        return "blocked_login" if "blocked" in statuses else "blocked"
    if result.status is AgentStatus.FAILED:
        return "tool_failed"
    if result.status is AgentStatus.EMPTY:
        return "no_result"
    return "partial"


def sentiment_of_text(text: str) -> float | None:
    """给外部留一个口子，避免各处再 import parsing。"""
    return sentiment_of(text)
