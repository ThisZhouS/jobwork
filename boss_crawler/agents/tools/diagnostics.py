"""诊断工具：报错日志写入。

要求是「所有 agent 都必须配这个工具」，用来写**两类东西**：

* 报错（异常、工具失败、返回码非 0）；
* 缺失数据 / 失败原因（「这家公司没查到工商信息，因为被限频」）。

写到哪里分三层，按可用性降级，保证任何环境都留得下痕迹：

1. ``ctx.option("store")`` 或 ``ctx.db`` 可用 → 写 ``agent_error`` 表；
2. 否则写 ``<log_dir>/agents.jsonl``（默认 ``.state/logs``）；
3. 连文件都写不了 → 退回 logging 模块，不抛异常。

**这个工具永远不应该让 agent 失败**，所以它自己吞掉所有异常。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ..base import AgentStatus
from .base import Tool, ToolBox, ToolResult, register_tool

_LOGGER = logging.getLogger(__name__)

LEVELS = ("error", "warn", "info")


class LogEventTool(Tool):
    """写一条诊断日志。"""

    name = "log_event"
    site = "内部"
    description = "写入报错日志与缺失数据/失败原因（每个 agent 必备）"
    params = ("message",)
    requires = ()

    async def call(self, box: ToolBox, message: str = "", level: str = "error",
                   status: str | None = None, code: str | None = None,
                   agent: str | None = None, tool: str | None = None,
                   context: Any = None, **_: Any) -> ToolResult:
        level = level if level in LEVELS else "error"
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "level": level,
            "agent": agent,
            "tool": tool,
            "status": status,
            "code": code,
            "message": str(message or "")[:2000],
            "context": context,
        }
        target = self._write(box, row)
        return ToolResult.ok_(self.name, {"written": target, **row},
                              notes=[f"日志已写入 {target}"])

    # ------------------------------------------------------------------ 落盘
    def _write(self, box: ToolBox, row: dict) -> str:
        ctx = box.ctx
        store = ctx.option("store")
        if store is None and ctx.db is not None:
            try:
                from ...store.app_store import AppStore

                store = AppStore(ctx.db)
            except Exception:  # noqa: BLE001
                store = None
        if store is not None:
            try:
                store.log_event(
                    agent=str(row.get("agent") or ""),
                    tool=row.get("tool"),
                    level=str(row.get("level") or "error"),
                    status=row.get("status"),
                    code=row.get("code"),
                    message=str(row.get("message") or ""),
                    context=row.get("context"),
                    run_id=ctx.option("run_id"),
                )
                return "数据库 agent_error"
            except Exception as exc:  # noqa: BLE001 - 落库失败继续走文件
                _LOGGER.debug("写 agent_error 失败：%s", exc)

        log_dir = Path(str(ctx.option("log_dir") or ".state/logs"))
        path = log_dir / "agents.jsonl"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            return str(path)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("诊断日志写入失败（已降级到 logging）：%s | %s", exc, row)
            _LOGGER.error("[%s] %s %s", row.get("agent"), row.get("level"), row.get("message"))
            return "logging"


async def record(box: ToolBox, message: str, *, level: str = "error",
                 status: AgentStatus | str | None = None, code: str | None = None,
                 agent: str | None = None, tool: str | None = None,
                 context: Any = None) -> ToolResult:
    """给 agent 内部用的便捷入口（不必再构造 ToolCall）。"""
    status_value = getattr(status, "value", status)
    return await LogEventTool().execute(box, message=message, level=level,
                                        status=status_value, code=code,
                                        agent=agent, tool=tool, context=context)


register_tool(LogEventTool())

