"""微博背调 agent。

抓取与解析都在 ``weibo_search`` 工具里；这里只汇总。
微博是事件驱动型信源，负面信号价值最高，情感由共享词表统一判定。
"""
from __future__ import annotations

from typing import Any

from ..base import AgentRequest
from ..registry import register
from ..toolagent import ToolAgent, ToolCall, sentiment_summary


class WeiboAgent(ToolAgent):
    name = "weibo"
    site = "微博"
    description = "调 weibo_search 工具，汇总微博上关于该公司的评价与负面事件"
    requires = ("http",)
    tools = (ToolCall("weibo_search", source="weibo"),)

    def extra_meta(self, results) -> dict[str, Any]:
        return {}


register(WeiboAgent)
