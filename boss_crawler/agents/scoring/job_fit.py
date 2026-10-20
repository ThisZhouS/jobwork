"""岗位适配度评分 agent —— **空框架，规则待定义**。

5 个维度与权重已声明（可自由改）。这里的设计意图不只是"给个分"，
而是将来能输出**具体提升方向**（``ScoreCard.advice``）。

写规则时的入口：``Rule.scorer`` 返回 0-100 或 ``None``（无数据）。
``scoring/rubric.py`` 备好了常用函数：
``coverage``（需求覆盖率）/ ``parse_years`` / ``experience_years`` /
``normalize_skills`` / ``gap_advice``（把技能缺口翻成一句可执行的话）/ ``interp``。

示例：

```python
from .rubric import coverage, normalize_skills

def score_skills(ctx):
    need = normalize_skills(ctx.job.get("skills"))
    if not need:
        return None
    return coverage(need, normalize_skills(ctx.resume.get("skills"))) * 100
```
"""
from __future__ import annotations

from ..base import Agent
from ..registry import register
from .framework import Rubric, Rule, ScoringAgentMixin


class JobFitAgent(ScoringAgentMixin, Agent):
    name = "job_fit"
    description = "岗位适配度评分与提升方向（框架就绪，规则待定义）"

    #: 岗位 agent 额外要求：能通过前端问用户，用来一起改进简历
    mandatory_tools = ("log_event", "ask_user")

    DIMENSIONS = (
        ("硬性条件", 3.0, "学历、年限这类不满足就基本没戏的门槛"),
        ("技能重合", 3.0, "JD 要求的技能在简历里的覆盖率"),
        ("经验年限", 2.0, "实际年限与要求年限的差距"),
        ("业务匹配", 2.0, "行业与业务方向是否对得上"),
        ("关键词覆盖", 1.0, "JD 高频词在简历里的命中率（ATS 视角）"),
    )

    #: 要问用户的问题（前端渲染成对话，用于改进简历）
    QUESTIONS = (
        "这个岗位里你最匹配的一段经历是什么？",
        "有哪项 JD 要求你能补上、但简历里还没写？",
        "期望薪资和这个岗位的区间差多少？",
    )

    def build_rubric(self, request) -> Rubric:
        return Rubric(rules=[
            Rule(name=name, weight=weight, hint=hint, scorer=None)
            for name, weight, hint in self.DIMENSIONS
        ])

    def subject_of(self, request, ctx) -> str:
        title = str(ctx.job.get("title") or ctx.job.get("name") or "岗位")
        company = str(ctx.job.get("company") or request.company_name or "")
        return f"{title} @ {company}".strip(" @")


register(JobFitAgent)
