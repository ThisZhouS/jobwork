"""阿里云云市场风险背调 agent。

只做一件事：调 ``aliyun_risk`` 工具，把行汇总成 findings。
地址/字段映射/AppCode 全在配置与工具里，这里不碰。

默认**不启用**：没买接口、没填 AppCode 时它会返回 BLOCKED 并说明缺什么。
它也不在默认平台列表里——要跑得显式指定 ``--platforms aliyun``。
"""
from __future__ import annotations

from ..registry import register
from ..toolagent import ToolAgent, ToolCall


class AliyunRiskAgent(ToolAgent):
    name = "aliyun"
    site = "阿里云云市场"
    description = "调云市场风险接口（司法涉诉/工商），按次计费，需 ALIYUN_APPCODE"
    requires = ("http",)
    tools = (ToolCall("aliyun_risk", source="aliyun"),)


register(AliyunRiskAgent)
