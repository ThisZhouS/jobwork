"""站点工具集合。导入即注册。

加一个站点 = 在这里多一行 import。
"""
from __future__ import annotations

from .tianyancha import (
    TianyanchaCompanyTool,
    TianyanchaRiskTool,
    TianyanchaSearchTool,
)
from .tieba import TiebaSearchTool
from .tyc import TycAskTool, TycBundleTool
from .weibo import WeiboSearchTool
from .zhihu import ZhihuSearchTool

__all__ = [
    "TianyanchaCompanyTool",
    "TianyanchaRiskTool",
    "TianyanchaSearchTool",
    "TiebaSearchTool",
    "TycAskTool",
    "TycBundleTool",
    "WeiboSearchTool",
    "ZhihuSearchTool",
]
