"""评分 agent：只有框架，规则待定义。

三个 agent 都**不含任何评分规则**——分值怎么算属于业务判断，留给你定义。
``framework.py`` 提供：

* ``Rule`` / ``Rubric`` —— 声明维度与权重，填 ``scorer`` 即生效；
* ``ScoreContext``      —— 规则里能读到的东西（profile/counts/findings/metrics/resume/job）；
* ``ScoringAgentMixin`` —— 把规则折算成 ``ScoreCard``，未定义规则给中性分并标注。

``rubric.py`` 里是写规则时常用的纯函数（区间插值、覆盖率、年限解析、缺口话术）。

============================  ==================================================
agent                         评什么（维度已声明，规则未填）
============================  ==================================================
``company_score``             公司值不值得去（消费上游背调证据）
``resume_score``              简历本身写得好不好
``job_fit``                   这份简历配这个岗位差在哪
============================  ==================================================
"""
from __future__ import annotations

from .company_score import CompanyScoreAgent
from .framework import (
    NEUTRAL,
    Rubric,
    Rule,
    ScoreContext,
    ScoringAgentMixin,
)
from .job_fit import JobFitAgent
from .resume_score import ResumeScoreAgent

__all__ = [
    "NEUTRAL",
    "CompanyScoreAgent",
    "JobFitAgent",
    "ResumeScoreAgent",
    "Rubric",
    "Rule",
    "ScoreContext",
    "ScoringAgentMixin",
]
