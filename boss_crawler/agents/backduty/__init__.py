"""背调 agent：调工具取证，产出 :class:`~boss_crawler.agents.base.Finding`。

六个 agent 都只是"调工具 + 汇总"，反爬与解析全在 ``agents/tools/`` 里：

===========================  ==================================================
agent                        调用的工具
===========================  ==================================================
``zhihu``                    ``zhihu_search``（需登录）
``tieba``                    ``tieba_search``（多数免登录）
``weibo``                    ``weibo_search``（移动端接口常免登录）
``tianyancha_web``           ``tianyancha_full``（免登录、零成本）
``tianyan_ai``               ``tyc_bundle``（tyc CLI 免费额度）
``cninfo``                   ``cninfo_notices``（巨潮公告，免鉴权，仅上市公司）
===========================  ==================================================

导入本包即完成注册（``boss_crawler.agents.registry`` 会自动加载它）。
"""
from __future__ import annotations

from ..toolagent import ToolAgent, ToolCall, rows_to_findings, sentiment_summary
from .cninfo import CninfoAgent
from .tianyan_ai import TianyanAiAgent
from .tianyancha_web import TianyanchaWebAgent
from .tieba import TiebaAgent
from .weibo import WeiboAgent
from .zhihu import ZhihuAgent

__all__ = [
    "CninfoAgent",
    "TianyanAiAgent",
    "TianyanchaWebAgent",
    "TiebaAgent",
    "ToolAgent",
    "ToolCall",
    "WeiboAgent",
    "ZhihuAgent",
    "rows_to_findings",
    "sentiment_summary",
]
