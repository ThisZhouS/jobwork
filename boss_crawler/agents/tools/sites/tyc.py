"""天眼AI 工具：走官方 ``tyc`` CLI 的**免费额度**。

为什么是 CLI 而不是网页对话：天眼AI 对外提供的就是 CLI/MCP 这种正规接入，
比逆向聊天框既稳又合规。工具里只调用 ``FREE_TOOLS`` 白名单，
付费/VIP 工具一律不碰。

需要一个自然语言总结时用 ``tyc_ask``；需要结构化字段时用 ``tyc_bundle``。
"""
from __future__ import annotations

from typing import Any

from ....providers.tyc_cli import FREE_TOOLS, TycCli, TycCliError
from ...base import AgentStatus
from ..base import Tool, ToolBox, ToolResult, register_tool

#: 一次拉取哪些免费工具（顺序即报告顺序）
BUNDLE_TOOLS: tuple[tuple[str, str], ...] = (
    ("registration", "company registration-info"),
    ("risk", "risk overview"),
    ("profile", "company profile"),
    ("scale", "company scale"),
    ("tags", "company tags"),
    ("ipr_score", "intellectual_property ipr-score"),
)


class TycBundleTool(Tool):
    name = "tyc_bundle"
    site = "天眼AI"
    description = "用 tyc CLI 免费工具取工商登记/风险总览/简介/规模/标签/知产评分"
    params = ("company",)
    requires = ("cli",)

    async def call(self, box: ToolBox, company: str = "", **_: Any) -> ToolResult:
        cli = _client(box)
        try:
            candidates = await cli.acall("company companies", company)
        except TycCliError as exc:
            return _degrade(self.name, exc, [])

        chosen = _first_name(candidates) or company
        notes: list[str] = []
        if chosen != company:
            notes.append(f"实体锚定到：{chosen}")

        bundle: dict[str, Any] = {}
        errors: list[str] = []
        for key, tool in BUNDLE_TOOLS:
            assert tool in FREE_TOOLS or tool.replace(" ", ".") in FREE_TOOLS, tool
            try:
                bundle[key] = await cli.acall(tool, chosen)
            except TycCliError as exc:
                if exc.kind in ("not_installed", "not_authed"):
                    return _degrade(self.name, exc, notes)
                errors.append(f"{tool} 失败：{exc}")

        if not bundle:
            return ToolResult.failed(self.name, "；".join(errors) or "所有免费工具都失败",
                                     notes=notes)
        status = AgentStatus.OK if not errors else AgentStatus.PARTIAL
        return ToolResult(tool=self.name, status=status,
                          data={"company": chosen, "bundle": bundle},
                          notes=notes + errors[:3])


class TycAskTool(Tool):
    name = "tyc_ask"
    site = "天眼AI"
    description = "把一句话问题交给天眼AI（CLI 对话式查询），返回其自然语言答案"
    params = ("question",)
    requires = ("cli",)

    async def call(self, box: ToolBox, question: str = "", **_: Any) -> ToolResult:
        cli = _client(box)
        try:
            answer = await cli.acall("ask", question)
        except TycCliError as exc:
            return _degrade(self.name, exc, [])
        if not answer:
            return ToolResult.empty(self.name)
        return ToolResult.ok_(self.name, answer)


def _client(box: ToolBox) -> TycCli:
    injected = box.ctx.option("cli")
    if injected is not None:
        return injected
    return TycCli(exec=box.ctx.option("exec"))


def _degrade(tool: str, exc: TycCliError, notes: list[str]) -> ToolResult:
    if exc.kind == "not_installed":
        return ToolResult.blocked(
            tool, str(exc),
            notes=[*notes, "安装后无需购买接口：npm install -g tyc-cli && tyc login"])
    if exc.kind == "not_authed":
        return ToolResult.blocked(
            tool, "天眼AI 未登录", notes=[*notes, str(exc), "先运行：tyc login"])
    return ToolResult.failed(tool, str(exc), notes=notes)


def _first_name(payload: Any) -> str | None:
    for item in _as_items(payload):
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _as_items(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("items", "data", "result", "list"):
            inner = value.get(key)
            if isinstance(inner, (list, dict)):
                found = _as_items(inner)
                if found:
                    return found
    return []


register_tool(TycBundleTool())
register_tool(TycAskTool())
