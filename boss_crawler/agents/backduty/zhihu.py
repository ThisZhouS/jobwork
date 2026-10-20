"""知乎背调 agent。

它自己不抓页面、不管反爬、不写解析——全部交给 ``zhihu_search`` 工具。
这里只做一件事：调工具，把返回的行汇总成 Finddings。
"""
from __future__ import annotations

from ..registry import register
from ..toolagent import ToolAgent, ToolCall


class ZhihuAgent(ToolAgent):
    name = "zhihu"
    site = "知乎"
    description = "调 zhihu_search 工具，汇总知乎上关于该公司的讨论（需登录）"
    requires = ("http",)
    tools = (ToolCall("zhihu_search", source="zhihu"),)


register(ZhihuAgent)
