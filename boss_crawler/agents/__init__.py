"""可组合的 agent 集合 + 工具层。

两层结构（这是本轮调整的核心）：

* **工具层** ``agents.tools``：负责"怎么拿到"。UA 轮换、节流、重试、
  cookie 登录态、浏览器兜底、被挡识别、解析、原始页落盘，全在这里。
* **agent 层**：负责"拿到什么、怎么总结"。背调 agent 只声明调哪些工具；
  评分 agent 目前只有框架，规则待定义。

靠 :mod:`boss_crawler.agents.registry` 组装，组合顺序由调用方决定::

    zhihu,tieba,weibo,tianyancha_web -> company_score
    resume_score -> job_fit

单独跑一个 agent::

    from boss_crawler.agents import AgentRequest, AgentContext, get
    result = await get("zhihu")().execute(AgentRequest(company_name="茶百道"), ctx)

只用工具（不经过 agent）::

    from boss_crawler.agents import ToolBox, get_tool
    box = ToolBox(ctx)
    rows = (await get_tool("tianyancha_search").execute(box, company="茶百道")).data
"""
from __future__ import annotations

from .base import (
    Agent,
    AgentContext,
    AgentKind,
    AgentRequest,
    AgentResult,
    AgentStatus,
    Dimension,
    Finding,
    MissingInput,
    ScoreCard,
    grade_of,
    merge_findings,
)
from .fetch import HttpFetcher, StealthBrowser, looks_blocked
from .registry import Pipeline, catalog, get, names, register, run_agents
from .toolagent import ToolAgent, ToolCall, rows_to_findings, sentiment_summary
from .tools import (
    Tool,
    ToolBox,
    ToolResult,
    get_tool,
    register_tool,
    tool_catalog,
    tool_names,
)

__all__ = [
    "Agent",
    "AgentContext",
    "AgentKind",
    "AgentRequest",
    "AgentResult",
    "AgentStatus",
    "Dimension",
    "Finding",
    "HttpFetcher",
    "MissingInput",
    "Pipeline",
    "ScoreCard",
    "StealthBrowser",
    "Tool",
    "ToolAgent",
    "ToolBox",
    "ToolCall",
    "ToolResult",
    "catalog",
    "get",
    "get_tool",
    "grade_of",
    "looks_blocked",
    "merge_findings",
    "names",
    "register",
    "register_tool",
    "rows_to_findings",
    "run_agents",
    "sentiment_summary",
    "settings",
    "tool_catalog",
    "tool_names",
]
