"""评分框架与空骨架的离线测试。

评分规则**还没定义**（等你来定），所以这里测的是框架本身：
维度声明、权重、规则空/有值/无数据/抛错时的行为、状态判定、
以及"填了规则就生效"这条通路。
"""
from __future__ import annotations

import pytest

from boss_crawler.agents import AgentContext, AgentRequest, AgentStatus, Finding
from boss_crawler.agents.registry import get as get_agent
from boss_crawler.agents.scoring import (
    NEUTRAL,
    CompanyScoreAgent,
    JobFitAgent,
    ResumeScoreAgent,
    Rubric,
    Rule,
    ScoreContext,
)
from boss_crawler.agents.scoring.rubric import (
    bullet_count,
    clamp,
    coverage,
    experience_years,
    gap_advice,
    interp,
    normalize_skills,
    parse_years,
    quantification_hits,
)


def _ctx(**kwargs) -> ScoreContext:
    request = AgentRequest(**kwargs)
    return ScoreContext.build(request)


# ---------------------------------------------------------------- Rule
def test_undefined_rule_gives_neutral_and_reason():
    dim = Rule("经营稳定性", weight=3.0, hint="看登记状态").evaluate(_ctx())
    assert dim.score == NEUTRAL
    assert "规则未定义" in dim.reason
    assert dim.weight == 3.0


def test_defined_rule_scores_and_clamps():
    rule = Rule("x", scorer=lambda ctx: 150.0)
    assert rule.evaluate(_ctx()).score == 100.0
    rule_low = Rule("y", scorer=lambda ctx: -20.0)
    assert rule_low.evaluate(_ctx()).score == 0.0


def test_rule_returning_none_means_no_data():
    dim = Rule("x", hint="看档案", scorer=lambda ctx: None).evaluate(_ctx())
    assert dim.score == NEUTRAL
    assert "无数据" in dim.reason


def test_rule_exception_degrades_to_neutral():
    def boom(ctx):
        raise ValueError("规则写错了")

    dim = Rule("x", scorer=boom).evaluate(_ctx())
    assert dim.score == NEUTRAL
    assert "规则执行出错" in dim.reason


def test_rule_reasoner_used_when_present():
    dim = Rule("x", scorer=lambda ctx: 80, reasoner=lambda ctx: "因为很稳").evaluate(_ctx())
    assert dim.score == 80
    assert dim.reason == "因为很稳"


def test_rule_defined_flag():
    assert not Rule("a").defined
    assert Rule("b", scorer=lambda ctx: 1).defined


# ---------------------------------------------------------------- Rubric
def test_rubric_build_card_weights():
    rubric = Rubric(rules=[
        Rule("甲", weight=3.0, scorer=lambda ctx: 100),
        Rule("乙", weight=1.0, scorer=lambda ctx: 20),
    ])
    card = rubric.build_card(_ctx(), "某公司")
    assert len(card.dimensions) == 2
    assert card.total == pytest.approx((100 * 3 + 20 * 1) / 4)
    assert card.grade in ("A", "B", "C", "D", "E")


def test_rubric_counts_undefined():
    rubric = Rubric(rules=[Rule("a"), Rule("b"), Rule("c", scorer=lambda ctx: 50)])
    assert rubric.defined_count == 1
    assert rubric.total_count == 3


def test_rubric_empty_gives_neutral_total():
    card = Rubric(rules=[]).build_card(_ctx(), "空")
    assert card.total == 0.0


# ---------------------------------------------------------------- ScoreContext
def test_context_extracts_profile_and_counts():
    finding = Finding(source="tianyancha_web", title="X",
                      meta={"profile": {"reg_status": "存续"},
                            "counts": {"法律诉讼": 2}})
    ctx = ScoreContext.build(AgentRequest(company_name="X", findings=[finding]))
    assert ctx.profile["reg_status"] == "存续"
    assert ctx.counts["法律诉讼"] == 2


def test_context_extracts_from_metrics():
    ctx = ScoreContext.build(AgentRequest(
        company_name="X",
        metrics={"tianyancha_full": {"profile": {"reg_status": "在业"},
                                     "counts": {"对外投资": 5}}}))
    assert ctx.profile["reg_status"] == "在业"
    assert ctx.counts["对外投资"] == 5


def test_context_keeps_resume_and_job():
    ctx = ScoreContext.build(AgentRequest(resume={"name": "张三"}, job={"title": "后端"}))
    assert ctx.resume["name"] == "张三"
    assert ctx.job["title"] == "后端"


# ---------------------------------------------------------------- 三个骨架
@pytest.mark.parametrize("agent_name,dims", [
    ("resume_score", ("完整度", "成果量化", "技能储备", "经历连续性", "表达结构")),
    ("job_fit", ("硬性条件", "技能重合", "经验年限", "业务匹配", "关键词覆盖")),
])
async def test_skeleton_declares_dimensions_and_is_partial(agent_name, dims):
    agent = get_agent(agent_name)()
    result = await agent.execute(
        AgentRequest(company_name="某公司", resume={"name": "张三"}, job={"title": "后端"}),
        AgentContext())
    assert result.status is AgentStatus.PARTIAL
    names = tuple(dim.name for dim in result.score.dimensions)
    assert names == dims
    for dim in result.score.dimensions:
        assert dim.score == NEUTRAL
        assert "规则未定义" in dim.reason
    assert result.score.notes
    assert "规则未定义" in " ".join(result.score.notes)
    assert result.meta["rules_defined"] == 0
    assert result.meta["rules_total"] == len(dims)


async def test_company_score_has_five_business_dimensions():
    """公司打分维度按方案定为 风险/待遇/压力/环境/福利。"""
    result = await get_agent("company_score")().execute(
        AgentRequest(company_name="某公司"), AgentContext())
    assert tuple(dim.name for dim in result.score.dimensions) == (
        "风险", "待遇", "压力", "环境", "福利")
    assert result.meta["rules_total"] == 5
    # 没有任何信号时不硬编：全部中性并说明无数据
    for dim in result.score.dimensions:
        assert dim.score == NEUTRAL
        assert "无数据" in dim.reason


async def test_skeleton_verdict_explains_state():
    result = await get_agent("resume_score")().execute(
        AgentRequest(resume={"name": "张三"}), AgentContext())
    assert "规则尚未定义" in result.score.verdict


async def test_filling_a_rule_activates_it():
    """把 scorer 填上之后应立刻算真分、状态不再因为该维度未定义。"""
    agent = ResumeScoreAgent()
    original = agent.build_rubric

    def patched(request):
        rubric = original(request)
        rubric.rules[0].scorer = lambda ctx: 88.0
        return rubric

    agent.build_rubric = patched
    result = await agent.execute(AgentRequest(resume={"name": "张三"}), AgentContext())
    assert result.score.dimensions[0].score == 88.0
    assert result.meta["rules_defined"] == 1
    assert result.status is AgentStatus.PARTIAL      # 还有 4 个维度没定义


async def test_all_rules_defined_makes_status_ok():
    agent = JobFitAgent()

    def patched(request):
        return Rubric(rules=[Rule("硬性条件", weight=1.0, scorer=lambda ctx: 70)])

    agent.build_rubric = patched
    result = await agent.execute(AgentRequest(job={"title": "后端"}), AgentContext())
    assert result.status is AgentStatus.OK
    assert result.score.total == pytest.approx(70.0)


async def test_subject_of_uses_profile_name():
    agent = CompanyScoreAgent()
    finding = Finding(source="s", title="X", meta={"profile": {"name": "四川百茶百道"}})
    result = await agent.execute(
        AgentRequest(findings=[finding]), AgentContext())
    assert result.score.subject == "四川百茶百道"


async def test_job_fit_subject_combines_title_and_company():
    result = await get_agent("job_fit")().execute(
        AgentRequest(company_name="某科技", job={"title": "后端工程师"}), AgentContext())
    assert "后端工程师" in result.score.subject


# ---------------------------------------------------------------- 规则工具函数
def test_clamp_and_interp():
    assert clamp(-5) == 0.0
    assert clamp(200) == 100.0
    assert interp(5, [(0, 0), (10, 100)]) == 50.0
    assert interp(5, []) == NEUTRAL


# ---------------------------------------------------------------- 公司五维规则
def _company_ctx(*, counts=None, findings=None, jobs_summary=None) -> ScoreContext:
    return ScoreContext.build(AgentRequest(
        company_name="某公司", findings=findings or [],
        metrics={"jobs_summary": jobs_summary} if jobs_summary else {}))


def _finding(title: str, sentiment: float | None = None):
    return Finding(source="s", title=title, sentiment=sentiment)


async def test_risk_drops_when_counts_and_negatives_grow():
    from boss_crawler.agents.scoring.company_score import score_risk

    clean = ScoreContext.build(AgentRequest(company_name="A"))
    clean.counts = {"法律诉讼": 0}
    risky = ScoreContext.build(AgentRequest(company_name="B"))
    risky.counts = {"失信": 3, "经营异常": 2, "行政处罚": 4}
    risky.findings = [_finding("欠薪仲裁", -1.0), _finding("跑路", -1.0)]

    assert score_risk(clean) > score_risk(risky)
    assert 0 <= score_risk(risky) <= 100


async def test_pay_uses_salary_and_wording():
    from boss_crawler.agents.scoring.company_score import score_pay

    high = _company_ctx(jobs_summary={"salary_max": 30000})
    low = _company_ctx(jobs_summary={"salary_max": 4000})
    assert score_pay(high) > score_pay(low)
    assert score_pay(_company_ctx()) is None          # 无信号 -> None

    bad = _company_ctx(findings=[_finding("长期欠薪", -1.0)])
    good = _company_ctx(findings=[_finding("年终奖按时发", 1.0)])
    assert score_pay(good) > score_pay(bad)


async def test_pressure_and_environment_from_text():
    from boss_crawler.agents.scoring.company_score import score_environment, score_pressure

    hard = _company_ctx(findings=[_finding("996 大小周 无偿加班 内卷", -1.0)])
    easy = _company_ctx(findings=[_finding("双休 氛围好 不加班", 1.0)])
    assert score_pressure(easy) > score_pressure(hard)
    assert score_environment(easy) > score_environment(hard)
    assert score_pressure(_company_ctx()) is None


async def test_welfare_from_tags_and_text():
    from boss_crawler.agents.scoring.company_score import score_welfare

    rich = _company_ctx(jobs_summary={"welfare": ["五险一金", "双休", "年终奖", "餐补", "体检"]})
    poor = _company_ctx(jobs_summary={"welfare": []})
    assert score_welfare(rich) is not None
    assert score_welfare(poor) is None or score_welfare(rich) > score_welfare(poor)


async def test_company_score_produces_numbers_with_evidence():
    from boss_crawler.agents.scoring.company_score import CompanyScoreAgent

    agent = CompanyScoreAgent()
    result = await agent.execute(
        AgentRequest(company_name="某公司",
                     findings=[_finding("欠薪 996 加班严重", -1.0)]),
        AgentContext())
    dims = {d.name: d.score for d in result.score.dimensions}
    assert dims["风险"] < NEUTRAL          # 有负面证据，风险项应低于中性
    assert result.score.total > 0


async def test_company_score_all_neutral_without_signal():
    result = await get_agent("company_score")().execute(
        AgentRequest(company_name="某公司"), AgentContext())
    assert result.score.total == pytest.approx(NEUTRAL)
    for dim in result.score.dimensions:
        assert dim.score == NEUTRAL
        assert "无数据" in dim.reason


def test_normalize_skills():
    assert normalize_skills("Python, Go、Redis") == ["python", "go", "redis"]
    assert normalize_skills(None) == []


def test_coverage_and_gap_advice():
    assert coverage(["python", "go"], ["python"]) == 0.5
    advice = gap_advice(["python", "go"], ["python"])
    assert advice and "go" in advice[0]


def test_parse_years_range_takes_lower_bound():
    assert parse_years("3-5年") == 3.0
    assert parse_years("3年以上") == 3.0


def test_experience_years_from_periods():
    years = experience_years([{"start": "2019-03", "end": "2022-06"}])
    assert years == pytest.approx(3.25, abs=0.05)


def test_quantification_and_bullets():
    assert quantification_hits("提升 30%，覆盖 300 万单") >= 2
    assert bullet_count("主导订单系统重构并上线\n支撑三百万单峰值流量\n带领五人小组完成交付") == 3
