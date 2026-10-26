"""评分框架（空框架，规则待你定义）。

刻意**不内置任何评分规则**：分值怎么算、权重怎么给属于业务判断，
先由使用方定义。框架只负责三件事：

1. 声明维度（名字 + 权重 + 一句该维度看什么）；
2. 把"填了规则的维度"折算成 :class:`~boss_crawler.agents.base.Dimension`；
3. 没填规则的维度给**中性分**并写明"规则未定义"，而不是悄悄按 0 分处理。

填规则的写法（这就是后续你要做的事）：

```python
def score_capital(ctx) -> float | None:
    wan = ctx.profile.get("reg_capital_wan")
    if wan is None:
        return None                      # 返回 None = 这个维度没数据
    return 90 if wan >= 10000 else 60

RUBRIC = Rubric(rules=[
    Rule("经营稳定性", weight=3.0, hint="登记状态、成立年限、注册资本",
         scorer=score_capital),
])
```

返回 ``None`` 表示"该维度这次没数据"，框架会给中性分 60 并标注原因。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..base import (
    AgentKind,
    AgentResult,
    AgentStatus,
    Dimension,
    ScoreCard,
    grade_of,
)

#: 没数据/没规则时的中性分。不用 0 或 100：那会把"不知道"伪装成"很差/很好"。
NEUTRAL = 60.0


@dataclass
class ScoreContext:
    """评分时可读的东西，统一放在这里，方便写规则。"""

    request: Any
    #: 上游背调 agent 的 findings
    findings: list[Any] = field(default_factory=list)
    #: 上游产出的结构化指标（如 {"tianyancha_full": {...}}）
    metrics: dict[str, Any] = field(default_factory=dict)
    #: 工商档案（首个带 profile 的 Finding.meta 或 metrics 里提取）
    profile: dict[str, Any] = field(default_factory=dict)
    #: 侧栏计数
    counts: dict[str, int] = field(default_factory=dict)
    resume: dict[str, Any] = field(default_factory=dict)
    job: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, request) -> "ScoreContext":
        findings = list(getattr(request, "findings", None) or [])
        metrics = dict(getattr(request, "metrics", None) or {})
        profile: dict[str, Any] = {}
        counts: dict[str, int] = {}
        for finding in findings:
            meta = getattr(finding, "meta", None) or {}
            if isinstance(meta.get("profile"), dict) and meta["profile"]:
                profile = meta["profile"]
            if isinstance(meta.get("counts"), dict) and meta["counts"]:
                counts = meta["counts"]
        for value in metrics.values():
            if not isinstance(value, dict):
                continue
            if not profile and isinstance(value.get("profile"), dict):
                profile = value["profile"]
            if not counts and isinstance(value.get("counts"), dict):
                counts = value["counts"]
            if not profile and isinstance(value.get("registration"), dict):
                profile = value["registration"]
        return cls(
            request=request,
            findings=findings,
            metrics=metrics,
            profile=profile,
            counts=counts,
            resume=dict(getattr(request, "resume", None) or {}),
            job=dict(getattr(request, "job", None) or {}),
        )


@dataclass
class Rule:
    """一个评分维度。

    ``scorer`` 为 ``None`` 表示"规则还没定义"——框架会输出中性分并明确标注。
    """

    name: str
    weight: float = 1.0
    hint: str = ""
    scorer: Callable[[ScoreContext], float | None] | None = None
    #: 可选：自定义理由文本，签名同 scorer，返回 str
    reasoner: Callable[[ScoreContext], str] | None = None

    @property
    def defined(self) -> bool:
        return self.scorer is not None

    def evaluate(self, ctx: ScoreContext) -> Dimension:
        return self.evaluate_with_state(ctx)[0]

    def evaluate_with_state(self, ctx: ScoreContext) -> tuple[Dimension, bool]:
        """返回 ``(维度, 是否有真实数据)``。

        中性分既可能来自"没规则"、也可能来自"没数据"，两者都不该被
        当成真实评分落库，所以要把覆盖状态单独带出来。
        """
        if self.scorer is None:
            return Dimension(self.name, NEUTRAL, self.weight,
                             f"规则未定义{('：' + self.hint) if self.hint else ''}"), False
        try:
            value = self.scorer(ctx)
        except Exception as exc:  # noqa: BLE001 - 规则写错不应该炸掉整个 agent
            return Dimension(self.name, NEUTRAL, self.weight,
                             f"规则执行出错（{type(exc).__name__}），按中性处理"), False
        if value is None:
            return Dimension(self.name, NEUTRAL, self.weight,
                             f"无数据，按中性处理{('：' + self.hint) if self.hint else ''}"), False
        score = max(0.0, min(100.0, float(value)))
        reason = ""
        if self.reasoner is not None:
            try:
                reason = str(self.reasoner(ctx))
            except Exception:  # noqa: BLE001
                reason = ""
        return Dimension(self.name, score, self.weight,
                         reason or self.hint or "已按规则计算"), True


@dataclass
class Rubric:
    """一套评分规则 = 若干维度。"""

    rules: list[Rule] = field(default_factory=list)

    @property
    def defined_count(self) -> int:
        return sum(1 for rule in self.rules if rule.defined)

    @property
    def total_count(self) -> int:
        return len(self.rules)

    def build_card(self, ctx: ScoreContext, subject: str) -> ScoreCard:
        return self.build_card_with_coverage(ctx, subject)[0]

    def build_card_with_coverage(self, ctx: ScoreContext,
                                 subject: str) -> tuple[ScoreCard, int]:
        evaluated = [rule.evaluate_with_state(ctx) for rule in self.rules]
        card = ScoreCard(subject=subject, dimensions=[dim for dim, _ in evaluated])
        card.finalize()
        return card, sum(1 for _, computed in evaluated if computed)


class ScoringAgentMixin:
    """评分 agent 的公共部分：声明规则 → 产出 ScoreCard。

    子类只需实现 :meth:`build_rubric`，并在里面按维度填 ``Rule``。
    规则全空时返回 PARTIAL，提醒"框架就绪但规则未定义"。

    与背调 agent 一致，评分 agent 也必须能写诊断（``log_event``），
    否则"为什么这家公司没分"就无从追查。
    """

    kind = AgentKind.SCORING
    name: str = ""
    produces: tuple[str, ...] = ("score",)
    mandatory_tools: tuple[str, ...] = ("log_event",)
    log_tool = "log_event"
    tools: tuple = ()

    def build_rubric(self, request) -> Rubric:  # pragma: no cover - 子类实现
        raise NotImplementedError

    async def run(self, request, ctx):  # type: ignore[override]

        rubric = self.build_rubric(request)
        score_ctx = ScoreContext.build(request)
        subject = self.subject_of(request, score_ctx)
        card, computed = rubric.build_card_with_coverage(score_ctx, subject)

        undefined = [rule.name for rule in rubric.rules if not rule.defined]
        notes: list[str] = []
        if undefined:
            notes.append("规则未定义：" + "、".join(undefined))
            notes.append("框架已就绪，在 scoring/ 对应文件里给 Rule.scorer 填一个函数即可生效")
        if computed == 0:
            notes.append("本次没有任何维度取到有效数据，分数仅代表中性假设")
        card.notes.extend(notes)
        card.verdict = card.verdict or _default_verdict(card, bool(undefined), computed)

        status = AgentStatus.OK if not undefined and computed else AgentStatus.PARTIAL
        meta = {"dimensions": {d.name: d.score for d in card.dimensions},
                "rules_defined": rubric.defined_count,
                "rules_total": rubric.total_count,
                "dimensions_computed": computed}
        meta.update(self.extra_meta(request, score_ctx, card))
        result = AgentResult(agent=self.name, status=status, score=card, notes=notes,
                             meta=meta)

        if status is not AgentStatus.OK:
            await self.diagnose(ctx, request, result, undefined, computed)
        return result

    async def diagnose(self, ctx, request, result: AgentResult,
                       undefined: list[str], computed: int = 0) -> None:
        """写诊断：为什么这个 agent 没给出可用分数。"""
        from ..tools import get_tool
        from ..toolagent import open_toolbox

        if undefined:
            message = "评分规则未定义：" + "、".join(undefined)
        elif computed == 0:
            message = "评分没有取到有效数据，未落库"
        else:
            message = result.error or "没有产出评分"
        try:
            async with open_toolbox(ctx) as box:
                await get_tool(self.log_tool).execute(
                    box, message=message, level="warn", status=result.status.value,
                    code="rules_undefined" if undefined else "no_score",
                    agent=self.name,
                    context={"company": getattr(request, "company_name", "")},
                )
        except Exception:  # noqa: BLE001 - 诊断永不影响主流程
            pass

    def subject_of(self, request, ctx: ScoreContext) -> str:
        return str(getattr(request, "company_name", "") or self.name)

    def extra_meta(self, request, ctx: ScoreContext, card: ScoreCard) -> dict[str, Any]:
        """子类加自己的字段（比如"是否劳务派遣"）。默认不加。"""
        return {}


def _default_verdict(card: ScoreCard, has_undefined: bool, computed: int) -> str:
    if has_undefined:
        return "评分规则尚未定义，当前分数仅代表中性假设"
    if computed == 0:
        return "本次没有取到有效数据，当前分数仅代表中性假设"
    return f"综合 {card.total:.1f} 分（{grade_of(card.total)}）"
