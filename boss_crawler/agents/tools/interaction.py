"""交互工具：向前端/用户提问。

岗位 agent 需要它：算完适配度之后，要能问用户「目标岗位最想强调哪段经历」，
再根据回答改进简历。

通道由调用方注入，工具本身不认识 UI：

* ``ctx.option("ask_user")`` 是一个 ``async (question, options) -> answer`` 回调，
  Electron 那边通过它把问题推给前端、等用户输入；
* 没有回调时（CLI 批处理），**不阻塞、不假装有人回答**，直接返回 ``EMPTY``
  并在 notes 里说明"无交互通道"。

这条降级很重要：流水线跑批时不能因为等人回答而卡死。
"""
from __future__ import annotations

import inspect
from typing import Any, Sequence

from ..base import AgentStatus
from .base import Tool, ToolBox, ToolResult, register_tool


class AskUserTool(Tool):
    """问用户一个问题，返回用户的回答。"""

    name = "ask_user"
    site = "内部"
    description = "向前端用户提问并获取回答（岗位 agent 改进简历时用）"
    params = ("question",)
    requires = ()

    async def call(self, box: ToolBox, question: str = "", options: Sequence[str] | None = None,
                   kind: str = "text", default: str | None = None, **_: Any) -> ToolResult:
        if not str(question or "").strip():
            return ToolResult.failed(self.name, "缺少 question")

        responder = box.ctx.option("ask_user")
        if responder is None:
            return ToolResult(
                tool=self.name, status=AgentStatus.EMPTY, data=None,
                error=None,
                notes=["无交互通道（未注入 ask_user 回调），已跳过提问，不阻塞流水线"],
                meta={"question": question, "options": list(options or []), "answered": False},
            )

        try:
            answer = responder(question, list(options or []))
            if inspect.isawaitable(answer):
                answer = await answer
        except Exception as exc:  # noqa: BLE001 - 交互失败不该炸掉 agent
            return ToolResult.failed(self.name, f"提问失败：{type(exc).__name__}: {exc}",
                                     meta={"question": question})

        if answer is None or (isinstance(answer, str) and not answer.strip()):
            return ToolResult(
                tool=self.name, status=AgentStatus.EMPTY, data=None,
                notes=["用户未回答（跳过）"],
                meta={"question": question, "answered": False},
            )

        answer_text = answer if isinstance(answer, str) else str(answer)
        return ToolResult.ok_(
            self.name,
            {"question": question, "answer": answer_text, "kind": kind},
            notes=[f"用户已回答：{answer_text[:60]}"],
            meta={"question": question, "answered": True, "default": default},
        )


async def ask(box: ToolBox, question: str, options: Sequence[str] | None = None,
              **kwargs: Any) -> str | None:
    """给 agent 内部用的便捷入口：拿不到回答就返回 None。"""
    result = await AskUserTool().execute(box, question=question, options=options, **kwargs)
    data = result.data if isinstance(result.data, dict) else None
    return str(data["answer"]) if data and data.get("answer") else None


register_tool(AskUserTool())

