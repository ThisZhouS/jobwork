"""应用层（编排 / 数据源 / 登录配置 / 存储键）的离线测试。

不连数据库：用一个记录调用的 FakeStore 替代 AppStore，
验证"每段该不该跑、按什么顺序跑、产出有没有落库"。
"""
from __future__ import annotations

import pytest

from boss_crawler.agents import AgentContext, AgentRequest, Finding, get
from boss_crawler.app.login import PLATFORMS, login, login_platforms, state_dir_for
from boss_crawler.app.pipeline import PLATFORM_AGENTS, Options, Pipeline, _finding_of
from boss_crawler.app.sources import (
    JobSource,
    get_source,
    register_source,
    reset_sources,
    run_source,
    source_names,
    sources,
)
from boss_crawler.store.app_store import dedupe_key


# ---------------------------------------------------------------- 数据源
def test_boss_source_registered_with_steps():
    source = get_source("boss")
    assert source.implemented
    steps = list(source.build_steps({"query": "Python", "city": "成都", "pages": 2}))
    assert [s[0] for s in steps] == ["crawl", "process", "db-load"]
    crawl = steps[0]
    assert "-q" in crawl and "Python" in crawl
    assert "-c" in crawl and "成都" in crawl
    assert "-p" in crawl and "2" in crawl


def test_boss_source_passes_ui_filters_to_crawler():
    source = get_source("boss")
    steps = source.build_steps({
        "query": "Python", "salary": "20-50K", "experience": "3-5年",
        "degree": "本科", "industry": "计算机软件",
    })
    crawl = list(steps)[0]
    for flag, value in (
        ("--salary", "20-50K"), ("--experience", "3-5年"),
        ("--degree", "本科"), ("--industry", "计算机软件"),
    ):
        assert flag in crawl
        assert crawl[crawl.index(flag) + 1] == value


def test_app_run_accepts_ui_filter_values():
    from boss_crawler.cli.parser import build_parser

    args = build_parser().parse_args([
        "app", "run", "--query", "Python", "--salary", "20-50K",
        "--experience", "3-5年", "--degree", "本科", "--industry", "计算机软件",
        "--no-crawl", "--json",
    ])
    assert args.salary == "20-50K"
    assert args.experience == "3-5年"
    assert args.degree == "本科"
    assert args.industry == "计算机软件"


def test_reserved_sources_are_declared_but_not_implemented():
    rows = {row["name"]: row for row in sources()}
    for name in ("lagou", "zhaopin", "51job"):
        assert name in rows
        assert rows[name]["implemented"] is False


async def test_unimplemented_source_is_skipped():
    result = await run_source("lagou", {"query": "x"})
    assert result["ok"] is False
    assert result["skipped"] is True


async def test_unknown_source_raises():
    with pytest.raises(KeyError):
        await run_source("不存在", {})


def test_duplicate_source_rejected():
    with pytest.raises(ValueError):
        register_source(JobSource(name="boss", label="重复"))


def test_register_and_reset_sources():
    reset_sources()
    try:
        assert "boss" in source_names()
        register_source(JobSource(name="demo", label="演示", implemented=False))
        assert "demo" in source_names()
        with pytest.raises(ValueError):
            register_source(JobSource(name="", label="空名"))
    finally:
        reset_sources()


# ---------------------------------------------------------------- 登录配置
@pytest.mark.parametrize("platform", ["tianyancha", "zhihu", "weibo", "tieba", "boss"])
def test_login_platforms_have_signal_cookies(platform):
    cfg = PLATFORMS[platform]
    assert cfg.url.startswith("https://")
    assert cfg.signal_cookies, f"{platform} 没有登录判定 cookie"
    assert state_dir_for(platform).name == platform


def test_login_platforms_list_shape():
    rows = login_platforms()
    assert {row["key"] for row in rows} == set(PLATFORMS)
    for row in rows:
        assert row["label"] and "note" in row


async def test_login_unknown_platform_returns_reason():
    result = await login("不存在的平台")
    assert result["ok"] is False
    assert "未知平台" in result["reason"]


# ---------------------------------------------------------------- 选项
def test_options_defaults_match_plan():
    options = Options()
    # tianyan_ai 要走 tyc CLI、aliyun 要 AppCode 且按次计费，都不进默认平台
    assert set(options.platforms) == set(PLATFORM_AGENTS) - {"tianyan_ai", "aliyun"}
    assert options.enable_crawl and options.enable_backduty
    assert options.enable_company_score and options.enable_job_fit
    assert options.enable_resume is False          # 简历默认关，用户确认后才开


def test_options_to_dict_hides_resume_content():
    options = Options(resume={"name": "张三", "phone": "13900000000"})
    payload = options.to_dict()
    assert "resume" not in payload
    assert isinstance(payload["platforms"], list)


def test_every_platform_maps_to_existing_agent():
    for platform, agent_name in PLATFORM_AGENTS.items():
        get(agent_name)                             # 不存在会抛 KeyError


# ---------------------------------------------------------------- 证据还原
def test_finding_of_roundtrip():
    row = {"agent": "zhihu", "title": "欠薪", "url": "https://x",
           "snippet": "三个月没发", "sentiment": -1.0, "weight": 2.0,
           "payload": {"k": "v"}, "published_at": "2021-06-01"}
    finding = _finding_of(row)
    assert isinstance(finding, Finding)
    assert finding.source == "zhihu"
    assert finding.sentiment == -1.0
    assert finding.meta["k"] == "v"


def test_finding_of_handles_missing_fields():
    finding = _finding_of({})
    assert finding.title == ""
    assert finding.weight == 1.0


# ---------------------------------------------------------------- 编排
class FakeStore:
    """记录所有写入，不碰数据库。"""

    def __init__(self):
        self.run_id = None
        self.finished = None
        self.evidence: list[tuple] = []
        self.scores: list[tuple] = []
        self.fits: list[tuple] = []
        self.events: list[dict] = []
        self.companies = [
            {"company_key": "k1", "company_name": "茶百道"},
            {"company_key": "k2", "company_name": "某科技"},
        ]
        self.jobs = [
            {"job_id": "j1", "title": "后端工程师", "company_name": "茶百道"},
        ]

    def start_run(self, options):
        self.run_id = 1
        return 1

    def finish_run(self, run_id, status, summary):
        self.finished = (run_id, status, summary)

    def company_targets(self, limit=50):
        return self.companies[:limit]

    def evidence_for(self, key, limit=None):
        return []

    def get_raw(self, key, agent):
        return None

    def jobs_summary(self, key):
        return {"count": 1, "salary_max": 20000, "welfare": ["双休"]}

    def jobs_for_fit(self, limit=50):
        return self.jobs[:limit]

    def latest_resume(self, confirmed_only=False):
        if confirmed_only:
            return None
        return None

    def save_evidence(self, key, agent, findings, run_id=None):
        self.evidence.append((key, agent, list(findings)))
        return len(list(findings))

    def save_company_score(self, key, card, run_id=None, extra=None):
        self.scores.append((key, card, extra))
        return len(self.scores)

    def save_job_fit(self, job_id, card, resume_id=None, run_id=None):
        self.fits.append((job_id, card))
        return len(self.fits)

    def save_resume(self, content, name=None, job_id=None, parent_id=None,
                    questions=None, answers=None, confirmed=False):
        self.resumes = getattr(self, "resumes", [])
        self.resumes.append({"content": content, "confirmed": confirmed,
                             "questions": questions, "answers": answers})
        return len(self.resumes)

    def log_event(self, **kwargs):
        self.events.append(kwargs)
        return len(self.events)


async def test_pipeline_scores_companies_when_stages_off():
    store = FakeStore()
    events: list[dict] = []
    options = Options(enable_crawl=False, enable_backduty=False,
                      enable_job_fit=False)
    result = await Pipeline(store, options, emit=events.append).run()
    assert result["status"] == "done"
    assert len(store.scores) == 2
    # 劳务派遣等独立字段要跟着打分一起落库
    assert store.scores[0][2] and "is_labor_dispatch" in store.scores[0][2]
    assert store.finished[1] == "done"
    assert any(event["type"] == "done" for event in events)


async def test_agent_errors_are_not_silently_skipped(monkeypatch):
    """队列里的真实异常要抛出去；串行阶段则记数并让运行标记为 partial。"""
    from boss_crawler.app import pipeline as pipeline_mod

    class BoomAgent:
        async def execute(self, request, ctx):
            raise RuntimeError("模型/网络故障")

    monkeypatch.setattr(pipeline_mod, "get", lambda name: BoomAgent)
    store = FakeStore()
    options = Options(enable_crawl=False, enable_backduty=False,
                      enable_company_score=False, enable_job_fit=False)
    pipe = pipeline_mod.Pipeline(store, options)
    request = AgentRequest(company_name="某公司")

    with pytest.raises(RuntimeError):
        await pipe._run_agent("boom", request, ctx=AgentContext())

    assert await pipe._run_agent("boom", request) is None
    assert pipe.summary["agent_errors"] == 1


async def test_pipeline_does_not_persist_score_without_signals():
    """全部维度都无数据时只是中性 60 分，不能当成真实评分落库。"""
    store = FakeStore()
    store.jobs_summary = lambda key: {"count": 0, "welfare": []}
    options = Options(enable_crawl=False, enable_backduty=False,
                      enable_job_fit=False)
    result = await Pipeline(store, options).run()
    assert result["status"] == "done"
    assert store.scores == []
    assert result["summary"]["scores"] == 0
    assert result["summary"]["scores_skipped"] == 2


async def test_pipeline_skips_job_fit_without_resume():
    store = FakeStore()
    options = Options(enable_crawl=False, enable_backduty=False,
                      enable_company_score=False)
    result = await Pipeline(store, options).run()
    assert result["summary"]["fits"] == 0
    assert store.fits == []


async def test_pipeline_resume_stage_writes_version():
    store = FakeStore()
    options = Options(enable_crawl=False, enable_backduty=False,
                      enable_company_score=False, enable_job_fit=False,
                      enable_resume=True, resume={"name": "张三"})
    result = await Pipeline(store, options).run()
    assert "resume" in result["summary"]
    assert result["summary"]["resume"]["ok"] is True
    # 产物必须落库（方案要求"存入数据库"），没问到用户时是草稿
    assert store.resumes and store.resumes[0]["content"]
    assert store.resumes[0]["confirmed"] is False
    assert result["summary"]["resume"]["confirmed"] is False


async def test_pipeline_records_failure_and_still_finishes():
    class BoomStore(FakeStore):
        def company_targets(self, limit=50):
            raise RuntimeError("库挂了")

    store = BoomStore()
    options = Options(enable_crawl=False, enable_backduty=True)
    result = await Pipeline(store, options).run()
    assert result["status"] == "failed"
    assert "库挂了" in result["summary"]["error"]
    assert store.finished[1] == "failed"


async def test_pipeline_injects_run_context():
    store = FakeStore()
    ctx = AgentContext()
    options = Options(enable_crawl=False, enable_backduty=False,
                      enable_company_score=False, enable_job_fit=False)
    await Pipeline(store, options, ctx=ctx).run()
    assert ctx.options["store"] is store
    assert ctx.options["run_id"] == 1


# ---------------------------------------------------------------- 去重键
def test_dedupe_key_prefers_url():
    assert dedupe_key("a", url="u1") == dedupe_key("a", url="u1")
    assert dedupe_key("a", url="u1") != dedupe_key("a", url="u2")


def test_dedupe_key_differs_by_agent():
    assert dedupe_key("a", url="u") != dedupe_key("b", url="u")


def test_dedupe_key_falls_back_to_title():
    key = dedupe_key("a", title="欠薪", published_at="2021-06-01")
    assert key == dedupe_key("a", title="欠薪", published_at="2021-06-01")
    assert key != dedupe_key("a", title="别的")


def test_dedupe_key_is_scoped_by_company():
    # 同一篇报道可能同时提到多家公司，但不能因此互相覆盖证据
    assert (dedupe_key("news", company_key="A", url="u1")
            != dedupe_key("news", company_key="B", url="u1"))


def test_dedupe_key_falls_back_to_snippet():
    key = dedupe_key("news", company_key="A", snippet="拖欠工资")
    assert key == dedupe_key("news", company_key="A", snippet="拖欠工资")
    assert key != dedupe_key("news", company_key="A", snippet="别的")
