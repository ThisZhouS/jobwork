"""简历评分 agent —— **空框架，规则待定义**。

5 个维度与权重已声明（可自由改）。填规则的入口是 ``Rule.scorer``：
从 ``ctx.resume`` 里读数，返回 0-100，或 ``None`` 表示这次没数据。

``scoring/rubric.py`` 里已经备好写规则常用的纯函数：
``quantification_hits`` / ``bullet_count`` / ``experience_years`` /
``normalize_skills`` / ``interp`` / ``clamp``。

示例：

```python
from .rubric import quantification_hits, interp

def score_quantified(ctx):
    text = str(ctx.resume.get("experience") or "")
    if not text:
        return None
    return interp(quantification_hits(text), [(0, 30), (3, 60), (8, 85)])
```
"""
from __future__ import annotations

from ..base import Agent
from ..registry import register
from .framework import Rubric, Rule, ScoringAgentMixin


class ResumeScoreAgent(ScoringAgentMixin, Agent):
    name = "resume_score"
    description = "简历多维度评分（框架就绪，规则待定义）"

    DIMENSIONS = (
        ("完整度", 3.0, "基本信息/求职意向/技能/经历/教育/项目 是否齐全"),
        ("成果量化", 3.0, "经历描述里有多少可验证的数字"),
        ("技能储备", 2.0, "技能项数量与技术广度"),
        ("经历连续性", 2.0, "总年限、段数、起止时间是否完整"),
        ("表达结构", 1.0, "条目化程度、概述与段落长度"),
    )

    def build_rubric(self, request) -> Rubric:
        return Rubric(rules=[
            Rule(name=name, weight=weight, hint=hint, scorer=None)
            for name, weight, hint in self.DIMENSIONS
        ])

    def subject_of(self, request, ctx) -> str:
        return str(ctx.resume.get("name") or ctx.resume.get("姓名") or "简历")


register(ResumeScoreAgent)
