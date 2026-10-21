"""巨潮资讯背调 agent —— 天眼查「风险提示」的免费平替。

它自己不请求、不解析，全部交给 ``cninfo_notices`` 工具；这里只把
「处罚/立案/诉讼/风险提示」这类公告汇总成 findings。

适用范围：**只对上市公司有效**。非上市公司查不到公告是正常的，
这时 agent 返回 EMPTY 并写明原因——不写"无风险"，因为信息不足 ≠ 安全。
"""
from __future__ import annotations

from ..registry import register
from ..toolagent import ToolAgent, ToolCall


class CninfoAgent(ToolAgent):
    name = "cninfo"
    site = "巨潮资讯"
    description = "查上市公司风险公告（处罚/立案/诉讼/风险提示），免鉴权、免登录"
    requires = ("http",)
    tools = (ToolCall("cninfo_notices", source="cninfo"),)


register(CninfoAgent)
