"""agent 内核的离线测试：契约、注册表、组合器、抓取层、天眼AI CLI 适配器。

不联网、不依赖真浏览器、不依赖真的装了 tyc。
"""
from __future__ import annotations

import json

import pytest

from boss_crawler.agents import (
    Agent,
    AgentContext,
    AgentKind,
    AgentRequest,
    AgentResult,
    AgentStatus,
    Dimension,
    Finding,
    HttpFetcher,
    MissingInput,
    Pipeline,
    ScoreCard,
    grade_of,
    looks_blocked,
    merge_findings,
    register,
)
from boss_crawler.agents.registry import catalog, get, load_errors, names
from boss_crawler.providers.tyc_cli import TycCli, TycCliError, _items, _parse_json, _payload


# ---------------------------------------------------------------- 契约
def test_grade_thresholds():
    assert grade_of(90) == "A"
    assert grade_of(85) == "A"
    assert grade_of(84.9) == "B"
    assert grade_of(70) == "B"
    assert grade_of(69) == "C"
    assert grade_of(55) == "C"
    assert grade_of(40) == "D"
    assert grade_of(39.9) == "E"


def test_scorecard_weights_total():
    card = ScoreCard(subject="测试")
    card.dimensions = [
        Dimension("a", 100, weight=3),
        Dimension("b", 0, weight=1),
    ]
    card.finalize()
    assert card.total == 75.0
    assert card.grade == "B"


def test_scorecard_zero_weight_is_safe():
    card = ScoreCard(subject="空")
    card.dimensions = [Dimension("a", 50, weight=0)]
    card.finalize()          # 除零不能炸
    assert card.total == 0.0 or card.total == 50.0


def test_scorecard_to_dict_shape():
    card = ScoreCard(subject="s", dimensions=[Dimension("d", 80)], verdict="还行").finalize()
    data = card.to_dict()
    assert set(data) == {"subject", "total", "grade", "verdict", "dimensions", "advice", "notes"}
    assert data["dimensions"][0]["score"] == 80.0


def test_finding_text_combines_title_and_snippet():
    assert Finding(source="x", title="欠薪", snippet="三个月没发").text == "欠薪 三个月没发"


def test_merge_findings_dedups_by_url():
    a = AgentResult(agent="a", status=AgentStatus.OK, findings=[Finding(source="z", url="u1")])
    b = AgentResult(agent="b", status=AgentStatus.OK, findings=[
        Finding(source="z", url="u1"), Finding(source="z", url="u2"),
    ])
    merged = merge_findings([a, b])
    assert [f.url for f in merged] == ["u1", "u2"]


def test_merge_findings_dedups_without_url():
    a = AgentResult(agent="a", status=AgentStatus.OK, findings=[Finding(source="z", title="t")])
    b = AgentResult(agent="b", status=AgentStatus.OK, findings=[Finding(source="z", title="t")])
    assert len(merge_findings([a, b])) == 1


def test_status_usable_only_ok_and_partial():
    assert AgentStatus.OK.is_usable and AgentStatus.PARTIAL.is_usable
    assert not AgentStatus.BLOCKED.is_usable
    assert not AgentStatus.EMPTY.is_usable


# ---------------------------------------------------------------- 入参
def test_request_require_company_raises():
    with pytest.raises(MissingInput):
        AgentRequest(company_name="  ").require_company()


def test_request_option_default():
    request = AgentRequest(options={"only": 1})
    assert request.option("only") == 1
    assert request.option("missing", "d") == "d"


def test_request_run_id_is_unique():
    assert AgentRequest().run_id != AgentRequest().run_id


# ---------------------------------------------------------------- 基类
class _EchoAgent(Agent):
    name = "_test_echo"
    kind = AgentKind.BACKDUTY
    description = "测试用"
    requires = ("http",)
    produces = ("findings",)

    async def run(self, request, ctx):
        return AgentResult.ok(self.name, findings=[Finding(source="t", title=request.company_name)])


class _BoomAgent(Agent):
    name = "_test_boom"

    async def run(self, request, ctx):
        raise ValueError("炸了")


class _InputAgent(Agent):
    name = "_test_input"

    async def run(self, request, ctx):
        request.require_company()
        return AgentResult.ok(self.name)


async def test_agent_execute_fills_elapsed():
    result = await _EchoAgent().execute(AgentRequest(company_name="x"), AgentContext())
    assert result.status is AgentStatus.OK
    assert result.elapsed_s >= 0


async def test_agent_execute_converts_exception_to_failed():
    result = await _BoomAgent().execute(AgentRequest(), AgentContext())
    assert result.status is AgentStatus.FAILED
    assert "ValueError" in result.error


async def test_agent_execute_converts_missing_input_to_failed():
    result = await _InputAgent().execute(AgentRequest(), AgentContext())
    assert result.status is AgentStatus.FAILED
    assert "输入不足" in result.error


def test_agent_describe_shape():
    data = _EchoAgent().describe()
    assert data["name"] == "_test_echo"
    assert data["requires"] == ["http"]
    assert data["produces"] == ["findings"]


# ---------------------------------------------------------------- 注册表
def test_register_and_get():
    register(_EchoAgent)
    assert get("_test_echo") is _EchoAgent
    assert "_test_echo" in names()


def test_register_rejects_duplicate_name():
    class Other(Agent):
        name = "_test_echo"

        async def run(self, request, ctx):
            return AgentResult.ok(self.name)

    with pytest.raises(ValueError, match="重复"):
        register(Other)


def test_register_rejects_empty_name():
    class NoName(Agent):
        async def run(self, request, ctx):
            return AgentResult.ok("x")

    with pytest.raises(ValueError, match="缺少 name"):
        register(NoName)


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        get("不存在的agent")


def test_catalog_filter_by_kind():
    register(_EchoAgent)
    backduty = catalog(AgentKind.BACKDUTY)
    assert all(item["kind"] == "backduty" for item in backduty)


def test_load_errors_is_dict():
    # 子包缺失时应能拿到错误说明，而不是抛异常
    errors = load_errors()
    assert isinstance(errors, dict)


# ---------------------------------------------------------------- 组合器
async def test_pipeline_runs_steps_in_order():
    order: list[str] = []

    class Step1(Agent):
        name = "_p1"

        async def run(self, request, ctx):
            order.append("p1")
            return AgentResult.ok(self.name, findings=[Finding(source="s1", title="a")])

    class Step2(Agent):
        name = "_p2"

        async def run(self, request, ctx):
            order.append("p2")
            # 应能读到上游 findings
            assert len(request.findings) == 1
            return AgentResult.ok(self.name)

    register(Step1)
    register(Step2)
    results = await Pipeline(["_p1", "_p2"]).run(AgentRequest(company_name="x"), AgentContext())
    assert order == ["p1", "p2"]
    assert len(results) == 2


async def test_pipeline_continues_after_failure_by_default():
    class Bad(Agent):
        name = "_pbad"

        async def run(self, request, ctx):
            raise RuntimeError("bad")

    register(Bad)
    register(_EchoAgent)
    results = await Pipeline(["_pbad", "_test_echo"]).run(AgentRequest(company_name="x"), AgentContext())
    assert len(results) == 2
    assert results[0].status is AgentStatus.FAILED
    assert results[1].status is AgentStatus.OK


async def test_pipeline_stop_on_failure():
    class Bad2(Agent):
        name = "_pbad2"

        async def run(self, request, ctx):
            raise RuntimeError("bad")

    register(Bad2)
    register(_EchoAgent)
    results = await Pipeline(["_pbad2", "_test_echo"], stop_on_failure=True).run(
        AgentRequest(company_name="x"), AgentContext())
    assert len(results) == 1


def test_pipeline_requires_steps():
    with pytest.raises(ValueError):
        Pipeline([])


# ---------------------------------------------------------------- 抓取层
def test_looks_blocked_on_short_html():
    assert looks_blocked("") is True
    assert looks_blocked("<html>x</html>") is True


def test_looks_blocked_on_captcha_words():
    body = "正常内容" * 400 + " 请输入验证码后继续访问"
    assert looks_blocked(body) is True


def test_looks_blocked_passes_normal_page():
    body = "这是一篇正常的公司评价页面。" * 200
    assert looks_blocked(body) is False


async def test_http_fetcher_retries_then_raises():
    calls = {"n": 0, "closed": False}

    class FakeResponse:
        status_code = 503
        text = "busy"

        def raise_for_status(self):
            raise RuntimeError("503")

    class FakeClient:
        async def get(self, url, **kwargs):
            calls["n"] += 1
            return FakeResponse()

        async def aclose(self):
            calls["closed"] = True

    fetcher = HttpFetcher(delay=0, retries=1)
    fetcher._client = FakeClient()
    with pytest.raises(RuntimeError, match="抓取失败"):
        await fetcher.get("https://example.com/x")
    assert calls["n"] == 2        # 首次 + 1 次重试
    await fetcher.close()
    assert calls["closed"] is True


async def test_http_fetcher_returns_text():
    class OkResponse:
        status_code = 200
        text = "<html>ok</html>"

        def raise_for_status(self):
            return None

    class FakeClient:
        async def get(self, url, **kwargs):
            return OkResponse()

        async def aclose(self):
            return None

    fetcher = HttpFetcher(delay=0)
    fetcher._client = FakeClient()
    assert await fetcher.get("https://example.com/y") == "<html>ok</html>"


# ---------------------------------------------------------------- 天眼AI CLI
def _fake_exec(code: int, out: str = "", err: str = ""):
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(list(args))
        return code, out, err

    runner.calls = calls      # type: ignore[attr-defined]
    return runner


def test_tyc_cli_anchor_parses_items():
    payload = {"data": {"items": [{"id": 1, "name": "茶百道", "creditCode": "91"}]}}
    cli = TycCli(exec=_fake_exec(0, json.dumps(payload)))
    assert cli.anchor("茶百道")[0]["name"] == "茶百道"


def test_tyc_cli_passes_compact_flag():
    runner = _fake_exec(0, '{"ok":1}')
    cli = TycCli(exec=runner)
    cli.call("company registration-info", "x")
    assert "--compact" in runner.calls[0]
    assert runner.calls[0][1:3] == ["company", "registration-info"]


def test_tyc_cli_detects_unauthed():
    cli = TycCli(exec=_fake_exec(1, "", "请求失败: 未配置 Authorization。请先运行：tyc init --authorization KEY"))
    with pytest.raises(TycCliError) as exc:
        cli.anchor("x")
    assert exc.value.kind == "not_authed"
    assert exc.value.needs_login is True


def test_tyc_cli_generic_error_is_not_login():
    cli = TycCli(exec=_fake_exec(2, "", "network unreachable"))
    with pytest.raises(TycCliError) as exc:
        cli.anchor("x")
    assert exc.value.kind == "cli_error"
    assert exc.value.needs_login is False


def test_tyc_cli_timeout_becomes_error():
    def boom(args, timeout):
        raise TimeoutError("too slow")

    cli = TycCli(exec=boom)
    with pytest.raises(TycCliError) as exc:
        cli.anchor("x")
    assert exc.value.kind == "timeout"


def test_tyc_cli_basic_bundle_isolates_failures():
    def runner(args, timeout):
        joined = " ".join(args)
        if "registration-info" in joined:
            return 0, '{"data":{"name":"X"}}', ""
        return 1, "", "boom"

    bundle = TycCli(exec=runner).basic_bundle("X")
    assert bundle["registration"]["name"] == "X"
    assert "risk" in bundle["errors"]


def test_parse_json_extracts_from_noisy_output():
    assert _parse_json('提示：查询中\n{"a": 1}\n完成') == {"a": 1}


def test_parse_json_raises_on_garbage():
    with pytest.raises(TycCliError) as exc:
        _parse_json("完全不是 JSON")
    assert exc.value.kind == "bad_json"


def test_payload_unwraps_data_key():
    assert _payload({"data": {"name": "X"}})["name"] == "X"
    assert _payload([{"a": 1}])["items"][0]["a"] == 1


def test_items_handles_nested_shapes():
    assert _items({"data": {"items": [{"a": 1}]}})[0]["a"] == 1
    assert _items([]) == []
    assert _items("nonsense") == []


def test_free_and_vip_tool_lists_are_disjoint():
    from boss_crawler.providers.tyc_cli import FREE_TOOLS, VIP_TOOLS

    assert set(FREE_TOOLS).isdisjoint(set(VIP_TOOLS))
