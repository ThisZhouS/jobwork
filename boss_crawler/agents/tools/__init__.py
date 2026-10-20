"""工具层：反爬能力都在这里，agent 只负责调工具与总结。

```
tools/
├── base.py          Tool 契约：ToolResult / Tool / ToolBox（反爬主干）/ 注册表
├── parsing.py       纯函数：文本清理、情感词表、JSON 抽取、日期归一
├── diagnostics.py   log_event：报错日志与缺失数据（每个 agent 必备）
├── interaction.py   ask_user：向前端用户提问（岗位 agent 用）
└── sites/           各站点工具，导入即注册
```

**为什么把反爬放进工具**：UA 轮换、节流、重试、cookie/登录态、浏览器兜底、
被挡识别、原始页面落盘——这些是"怎么拿到"，与"拿到后怎么解读"无关。
分开之后，换反爬策略只需改 :class:`ToolBox`，八个 agent 一行不动。
"""
from __future__ import annotations

from .base import (
    FetchOutcome,
    Tool,
    ToolBox,
    ToolResult,
    get_tool,
    register_tool,
    reset_tools,
    tool_catalog,
    tool_names,
)
from .parsing import (
    clip,
    dedupe,
    dedupe_rows,
    make_finding,
    negative_ratio,
    normalize_date,
    sentiment_of,
    sentiment_weight,
    strip_tags,
)
from . import diagnostics  # noqa: F401  导入即注册 log_event
from . import interaction  # noqa: F401  导入即注册 ask_user
from . import sites  # noqa: F401  导入即注册各站点工具
from .diagnostics import record
from .interaction import ask

__all__ = [
    "FetchOutcome",
    "Tool",
    "ToolBox",
    "ToolResult",
    "ask",
    "clip",
    "dedupe",
    "dedupe_rows",
    "get_tool",
    "make_finding",
    "negative_ratio",
    "normalize_date",
    "record",
    "register_tool",
    "reset_tools",
    "sentiment_of",
    "sentiment_weight",
    "strip_tags",
    "tool_catalog",
    "tool_names",
]
