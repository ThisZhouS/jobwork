"""百度贴吧背调 agent。

抓取与解析都在 ``tieba_search`` 工具里；这里只汇总。
"""
from __future__ import annotations

from ..registry import register
from ..toolagent import ToolAgent, ToolCall


class TiebaAgent(ToolAgent):
    name = "tieba"
    site = "百度贴吧"
    description = "调 tieba_search 工具，汇总贴吧里关于该公司的帖子"
    requires = ("http",)
    tools = (ToolCall("tieba_search", source="tieba"),)


register(TiebaAgent)
