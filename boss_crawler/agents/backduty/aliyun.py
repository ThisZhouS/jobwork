"""阿里云云市场工商信息背调 agent。

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
    description = "调云市场工商信息接口（AppCode 认证、按次计费）"
    requires = ("http",)
    tools = (
        ToolCall(
            "aliyun_risk",
            source="aliyun",
            params=lambda request: {
                "company": request.require_company(),
                "profile": "business",
            },
        ),
    )


register(AliyunRiskAgent)
