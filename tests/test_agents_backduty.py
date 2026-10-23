"""背调 agent 与工具层的离线测试。

架构变了：解析和反爬都在 ``agents/tools/``，agent 只调工具 + 汇总。
所以这里分两层测：
1. 工具层——注册表、契约、各站点解析、被挡判定、降级；
2. agent 层——状态判定、Finding 生成与去重。
全部用假 http/cli，不联网。
"""
from __future__ import annotations

import json

import pytest

from boss_crawler.agents import AgentContext, AgentRequest, AgentStatus
from boss_crawler.agents.registry import get as get_agent
from boss_crawler.agents.toolagent import (
    ToolAgent,
    ToolCall,
    describe_data,
    open_toolbox,
    rows_to_findings,
    sentiment_summary,
)
from boss_crawler.agents.tools import (
    Tool,
    ToolBox,
    ToolResult,
    get_tool,
    register_tool,
    tool_catalog,
    tool_names,
)
from boss_crawler.agents.tools.parsing import (
    clip,
    dedupe_rows,
    extract_json_after,
    make_finding,
    negative_ratio,
    normalize_date,
    regex_field,
    sentiment_of,
    strip_tags,
)
from boss_crawler.agents.tools.sites.tianyancha import (
    build_result_dict,
    parse_company_list,
    parse_counts,
    parse_risk_rows,
)
from boss_crawler.agents.tools.sites.tieba import (
    parse_tieba_bar,
    parse_tieba_rendered,
    parse_tieba_search,
)
from boss_crawler.agents.tools.sites.weibo import parse_weibo_html, parse_weibo_json
from boss_crawler.agents.backduty.relevance import (
    filter_findings,
    normalize_summary,
    parse_indices,
)
from boss_crawler.agents.tools.sites.zhihu import (
    object_url,
    parse_search_html,
    parse_search_json,
    timestamp_to_date,
)

PAD = "<!-- " + "x" * 900 + " -->"


def padded(body: str) -> str:
    return f"<html><body>{PAD}{body}</body></html>"


class FakeHttp:
    """按 URL 片段返回预设内容。"""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url: str, **kwargs):
        self.calls.append(url)
        for fragment, body in self.routes.items():
            if fragment in url:
                return body
        raise RuntimeError("404 not found")

    async def close(self):
        return None


class FakeCli:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    async def acall(self, tool: str, *args, **kwargs):
        self.calls.append(tool)
        value = self.responses.get(tool)
        if isinstance(value, Exception):
            raise value
        return value if value is not None else {}


class FakeStore:
    """记录写入，不碰数据库。"""

    def __init__(self):
        self.raw: list[tuple] = []
        self.events: list[dict] = []

    def save_raw(self, company_key, agent, payload, run_id=None):
        self.raw.append((company_key, agent, payload, run_id))

    def log_event(self, **kwargs):
        self.events.append(kwargs)
        return len(self.events)


# ---------------------------------------------------------------- 工具注册表
def test_all_site_tools_registered():
    names = tool_names()
    for expected in ("zhihu_search", "tieba_search", "weibo_search",
                     "tianyancha_search", "tianyancha_company",
                     "tianyancha_risk", "tianyancha_full",
                     "tyc_bundle", "tyc_ask"):
        assert expected in names


def test_tool_catalog_shape():
    for row in tool_catalog():
        assert row["name"] and row["description"]
        assert isinstance(row["params"], list)
        assert isinstance(row["requires"], list)


def test_get_tool_unknown_raises():
    with pytest.raises(KeyError):
        get_tool("不存在的工具")


def test_duplicate_tool_name_rejected():
    class Dup(Tool):
        name = "zhihu_search"

        async def call(self, box, **params):      # pragma: no cover
            return ToolResult.ok_("zhihu_search")

    with pytest.raises(ValueError):
        register_tool(Dup())


def test_empty_tool_name_rejected():
    class Nameless(Tool):
        async def call(self, box, **params):      # pragma: no cover
            return ToolResult.ok_("x")

    with pytest.raises(ValueError):
        register_tool(Nameless())


# ---------------------------------------------------------------- ToolResult
def test_tool_result_factories():
    assert ToolResult.ok_("t", 1).ok
    assert ToolResult.partial("t", 1).ok
    assert ToolResult.empty("t").status is AgentStatus.EMPTY
    assert ToolResult.blocked("t", "x").status is AgentStatus.BLOCKED
    assert not ToolResult.failed("t", "x").ok
    assert ToolResult.empty("t").usable
    assert not ToolResult.blocked("t", "x").usable


async def test_tool_execute_validates_params():
    result = await get_tool("zhihu_search").execute(_box(), company="")
    assert result.status is AgentStatus.FAILED
    assert "缺少参数" in result.error


async def test_tool_execute_catches_exceptions():
    class Boom(Tool):
        name = "boom_tool"
        params = ()

        async def call(self, box, **params):
            raise RuntimeError("炸了")

    result = await Boom().execute(_box())
    assert result.status is AgentStatus.FAILED
    assert "RuntimeError" in result.error


def test_tool_describe():
    described = get_tool("tieba_search").describe()
    assert described["name"] == "tieba_search"
    assert "company" in described["params"]


def _box(routes: dict[str, str] | None = None, **options):
    return ToolBox(AgentContext(http=FakeHttp(routes or {}), options={"no_browser": True, **options}))


# ---------------------------------------------------------------- 解析纯函数
def test_sentiment_negative_and_positive():
    assert sentiment_of("这家公司欠薪还裁员") == -1.0
    assert sentiment_of("福利好双休不加班，值得去") == 1.0
    assert sentiment_of("公司在北京") is None


def test_sentiment_negative_dominates_when_mixed():
    assert sentiment_of("欠薪但也涨薪") == -1.0


def test_strip_tags_removes_scripts():
    out = strip_tags('<div>a<script>var x=1</script><b>b</b>&amp;c</div>')
    assert "var x" not in out and "b" in out


def test_clip_respects_limit():
    assert len(clip("第一句。第二句。" * 40, 50)) <= 51


def test_normalize_date_formats():
    assert normalize_date("2021年3月5日") == "2021-03-05"
    assert normalize_date("2021/03/05") == "2021-03-05"
    assert normalize_date("无日期") is None


def test_regex_field_decodes_unicode_escape():
    assert regex_field('{"name":"\\u67d0\\u516c\\u53f8"}', "name") == "某公司"


def test_extract_json_after_nested():
    assert extract_json_after('x "data": {"a": [1,2]} y', "data") == {"a": [1, 2]}


def test_dedupe_rows_by_url():
    rows = [{"url": "u1"}, {"url": "u1"}, {"url": "u2"}]
    assert [r["url"] for r in dedupe_rows(rows)] == ["u1", "u2"]


def test_negative_ratio():
    items = [make_finding("s", title="欠薪"), make_finding("s", title="福利好")]
    assert 0.0 < negative_ratio(items) <= 1.0
    assert negative_ratio([]) == 0.0


# ---------------------------------------------------------------- 知乎工具
def test_zhihu_parse_json_answer():
    payload = json.dumps({"data": [{"object": {
        "type": "answer", "id": 99, "question": {"id": 123, "name": "茶百道怎么样"},
        "author": {"name": "某人"}, "created_time": 1600000000,
        "content": "加班多但薪资尚可",
    }}]})
    rows = parse_search_json(payload, "茶百道")
    assert rows and "question/123" in rows[0]["url"]
    assert rows[0]["author"] == "某人"
    assert rows[0]["published_at"]


def test_zhihu_object_url_falls_back_to_empty():
    assert object_url({}, "unknown") == ""


def test_zhihu_timestamp_to_date():
    assert timestamp_to_date(1600000000)
    assert timestamp_to_date("2021-03-05") == "2021-03-05"
    assert timestamp_to_date(None) is None
    assert timestamp_to_date("abc") is None


def test_relevance_parse_indices():
    assert parse_indices("[1, 3]", 4) == [1, 3]
    assert parse_indices("结果：[]", 4) == []
    assert parse_indices("[1, 9]", 4) == [1]
    assert parse_indices("没有数组", 4) is None


async def test_relevance_without_model_keeps_all():
    from boss_crawler.agents.base import Finding

    items = [Finding(source="zhihu", title="a"), Finding(source="zhihu", title="b")]
    kept, info = await filter_findings(items, "某公司", AgentContext())
    assert kept == items
    assert info["judged"] is False
    assert "模型不可用" in info["reason"]


def test_summary_unwraps_double_encoded_json():
    inner = {"summary": "一句话结论", "points": [{"topic": "薪资"}],
             "risk_level": "low"}
    outer = json.dumps({"summary": json.dumps(inner, ensure_ascii=False),
                        "points": []}, ensure_ascii=False)
    parsed = normalize_summary(outer)
    assert parsed is not None
    assert parsed["summary"] == "一句话结论"
    assert parsed["risk_level"] == "low"


def test_zhihu_parse_html_uses_question_anchor():
    rows = parse_search_html('<a href="/question/456">茶百道值得去吗</a>' + "补充" * 40, "茶百道")
    assert rows and rows[0]["url"].startswith("https://www.zhihu.com/question/456")


async def test_zhihu_tool_ok():
    payload = json.dumps({"data": [{"object": {"type": "answer", "id": 1,
                                                "question": {"id": 2}, "content": "茶百道欠薪三个月"}}]})
    result = await get_tool("zhihu_search").execute(_box({"zhihu.com": payload}), company="茶百道")
    assert result.status is AgentStatus.OK
    assert result.data


async def test_zhihu_tool_blocked_on_error_payload():
    payload = json.dumps({"error": {"message": "请先登录"}})
    result = await get_tool("zhihu_search").execute(_box({"zhihu.com": payload}), company="茶百道")
    assert result.status is AgentStatus.BLOCKED


# ---------------------------------------------------------------- 贴吧工具
def test_tieba_search_parses_blocks():
    html = ('<div class="s_post"><a href="/p/111">茶百道工资发不出来？</a>'
            '<div>2021-06-01 有人爆料</div></div>')
    rows = parse_tieba_search(html, "茶百道")
    assert rows and rows[0]["url"] == "https://tieba.baidu.com/p/111"


def test_tieba_bar_parses_post_links():
    rows = parse_tieba_bar('<a href="/p/222">茶百道加盟避雷</a>' + "楼层" * 30, "茶百道")
    assert rows and rows[0]["url"].endswith("/p/222")


def test_tieba_rendered_pairs_cards_with_absolute_links():
    html = (
        '<div class="thread-item"><span class="thread-title">茶百道加盟避雷</span>'
        '<span class="post-num">12</span></div>'
        '<div class="thread-item"><span class="thread-title">茶百道工资拖欠</span></div>'
        '<a href="https://tieba.baidu.com/p/111?fr=frs">x</a>'
        '<a href="https://tieba.baidu.com/p/222?fr=frs">x</a>'
    )
    rows = parse_tieba_rendered(html, "茶百道")
    assert len(rows) == 2
    assert rows[0]["url"].endswith("/p/111")
    assert "加盟避雷" in rows[0]["title"]


def test_tieba_ignores_short_anchor():
    assert parse_tieba_bar('<a href="/p/333">短</a>', "x") == []


async def test_tieba_tool_empty_when_nothing():
    result = await get_tool("tieba_search").execute(
        _box({"tieba.baidu.com": padded("<div>暂无帖子</div>")}), company="查无此司")
    assert result.status is AgentStatus.EMPTY


# ---------------------------------------------------------------- 微博工具
def test_weibo_json_walks_nested_cards():
    payload = json.dumps({"ok": 1, "data": {"cards": [
        {"card_type": 9, "mblog": {"id": "1", "text": "茶百道欠薪", "user": {"screen_name": "甲"},
                                   "created_at": "2021-05-01"}},
        {"card_group": [{"card_type": 9, "mblog": {"id": "2", "text": "福利还可以",
                                                   "user": {"screen_name": "乙"}}}]},
    ]}})
    rows = parse_weibo_json(payload, "茶百道")
    assert len(rows) == 2
    assert rows[0]["author"] == "甲"


def test_weibo_json_rejects_not_ok():
    assert parse_weibo_json(json.dumps({"ok": 0, "msg": "请先登录"}), "x") == []
    assert parse_weibo_json("垃圾", "x") == []


def test_weibo_html_parses_detail_links():
    rows = parse_weibo_html('<a href="//m.weibo.cn/detail/123">这条在说公司欠薪跑路</a>', "x")
    assert rows and rows[0]["url"].startswith("https://m.weibo.cn/detail/123")


async def test_weibo_tool_blocked_when_ok_zero():
    payload = json.dumps({"ok": 0, "msg": "请先登录"})
    result = await get_tool("weibo_search").execute(_box({"weibo.cn": payload}), company="茶百道")
    assert result.status is AgentStatus.BLOCKED


# ---------------------------------------------------------------- 天眼查工具
def test_parse_company_list():
    html = ('<a href="https://www.tianyancha.com/company/4158787537">四川百茶百道实业股份有限公司</a>'
            '<a href="/company/4211423805">成都茶百道餐饮管理有限公司</a>')
    rows = parse_company_list(html)
    assert len(rows) == 2 and rows[0]["id"] == "4158787537"


def test_parse_company_list_skips_short():
    assert parse_company_list('<a href="/company/1">短</a>') == []


def test_build_result_dict_prefers_official_name():
    html = json.dumps({"creditCode": "9111X", "name": "某科技有限公司"})
    result = build_result_dict(html, company_id="1", fallback_name="兜底")
    assert result["creditCode"] == "9111X"
    assert result["name"] == "某科技有限公司"


def test_parse_counts_max_and_999plus():
    counts = parse_counts("<div>法律诉讼1</div><div>法律诉讼3</div><div>商标信息999+</div>")
    assert counts["法律诉讼"] == 3
    assert counts["商标信息"] == 999


def test_parse_risk_rows():
    rows = parse_risk_rows("<div>2021-06-01 因广告违法被处罚 决定书某号</div>", "经营风险")
    assert rows and rows[0]["risk_type"] == "abnormal"


async def test_tianyancha_search_tool_ok():
    html = padded('<a href="/company/1">某科技有限公司</a>')
    result = await get_tool("tianyancha_search").execute(
        _box({"/search": html}), company="某科技有限公司")
    assert result.status is AgentStatus.OK
    assert result.data[0]["id"] == "1"


async def test_tianyancha_search_tool_blocked_on_shell():
    """壳页面里连查询词都没有 -> BLOCKED，而不是 EMPTY。"""
    shell = padded("<nav>首页 登录/注册</nav>")
    result = await get_tool("tianyancha_search").execute(
        _box({"/search": shell}), company="某公司")
    assert result.status is AgentStatus.BLOCKED


async def test_tianyancha_search_tool_empty_when_searched():
    body = padded('<input value="不存在的公司"><div>没有找到</div>')
    result = await get_tool("tianyancha_search").execute(
        _box({"/search": body}), company="不存在的公司")
    assert result.status is AgentStatus.EMPTY


async def test_tianyancha_full_tool_returns_profile_and_counts():
    search = padded('<a href="/company/4158787537">四川百茶百道实业股份有限公司</a>')
    page = padded(json.dumps({"creditCode": "91510100X", "regStatus": "存续",
                              "name": "四川百茶百道实业股份有限公司"})
                  + "<div>法律诉讼1</div><div>对外投资10</div>")
    routes = {"/search": search, "/sifa": padded("<div>2021-06-01 某案</div>"),
              "/jingxian": padded("<div>2021-07-02 某异常</div>"),
              "/company/4158787537": page}
    result = await get_tool("tianyancha_full").execute(_box(routes), company="四川百茶百道实业股份有限公司")
    assert result.status is AgentStatus.OK
    assert result.data["profile"]["credit_code"] == "91510100X"
    assert result.data["counts"]["对外投资"] == 10
    assert result.data["risks"]


# ---------------------------------------------------------------- 天眼AI 工具
def _cli_ok():
    return FakeCli({
        "company companies": {"items": [{"name": "四川百茶百道实业股份有限公司"}]},
        "company registration-info": {"data": {"name": "百茶百道", "regStatus": "存续"}},
        "risk overview": {"data": {"自身风险": 3}},
        "intellectual_property ipr-score": {"data": {"score": 88}},
    })


async def test_tyc_bundle_tool_ok():
    box = ToolBox(AgentContext(options={"cli": _cli_ok(), "no_browser": True}))
    result = await get_tool("tyc_bundle").execute(box, company="茶百道")
    assert result.status is AgentStatus.OK
    assert result.data["bundle"]["registration"]


async def test_tyc_bundle_blocked_when_not_installed():
    from boss_crawler.providers.tyc_cli import TycCliError

    cli = FakeCli({"company companies": TycCliError("未安装", kind="not_installed")})
    box = ToolBox(AgentContext(options={"cli": cli, "no_browser": True}))
    result = await get_tool("tyc_bundle").execute(box, company="X")
    assert result.status is AgentStatus.BLOCKED
    assert any("npm install" in note for note in result.notes)


async def test_tyc_bundle_blocked_when_not_authed():
    from boss_crawler.providers.tyc_cli import TycCliError

    cli = FakeCli({"company companies": TycCliError("未配置 Authorization", kind="not_authed")})
    box = ToolBox(AgentContext(options={"cli": cli, "no_browser": True}))
    result = await get_tool("tyc_bundle").execute(box, company="X")
    assert result.status is AgentStatus.BLOCKED
    assert any("tyc login" in note for note in result.notes)


async def test_tyc_bundle_only_calls_free_tools():
    cli = _cli_ok()
    box = ToolBox(AgentContext(options={"cli": cli, "no_browser": True}))
    await get_tool("tyc_bundle").execute(box, company="茶百道")
    from boss_crawler.providers.tyc_cli import VIP_TOOLS

    for tool in cli.calls:
        assert tool.replace(" ", ".") not in VIP_TOOLS, f"调了付费工具 {tool}"


# ---------------------------------------------------------------- agent 层
def test_rows_to_findings_computes_sentiment():
    findings = rows_to_findings(
        [{"title": "公司欠薪", "url": "u1", "snippet": "三个月没发", "company": "X"}], "tieba")
    assert findings[0].sentiment == -1.0
    assert findings[0].source == "tieba"


def test_rows_to_findings_skips_non_dict():
    assert rows_to_findings(["垃圾", None], "s") == []


def test_sentiment_summary_counts():
    findings = rows_to_findings([
        {"title": "欠薪", "url": "a"}, {"title": "福利好", "url": "b"},
        {"title": "在北京", "url": "c"},
    ], "s")
    summary = sentiment_summary(findings)
    assert summary["total"] == 3
    assert summary["negative"] == 1
    assert summary["positive"] == 1


def test_describe_data_includes_counts():
    text = describe_data({"profile": {"reg_status": "存续"}, "counts": {"法律诉讼": 1}})
    assert "存续" in text and "法律诉讼1" in text


async def test_zhihu_agent_summarizes_tool_rows():
    payload = json.dumps({"data": [{"object": {"type": "answer", "id": 1,
                                                "question": {"id": 2}, "content": "茶百道欠薪三个月"}}]})
    agent = get_agent("zhihu")()
    result = await agent.execute(AgentRequest(company_name="茶百道"),
                                 AgentContext(http=FakeHttp({"zhihu.com": payload}),
                                              options={"no_browser": True}))
    assert result.status is AgentStatus.OK
    assert result.findings[0].source == "zhihu"
    assert result.findings[0].sentiment == -1.0
    assert "zhihu_search" in result.meta["tools"]


async def test_agent_requires_company():
    result = await get_agent("zhihu")().execute(AgentRequest(), AgentContext())
    assert result.status is AgentStatus.FAILED
    assert "输入不足" in result.error


async def test_agent_dedupes_findings():
    payload = json.dumps({"data": [
        {"object": {"type": "answer", "id": 1, "question": {"id": 2}, "content": "茶百道欠薪"}},
        {"object": {"type": "answer", "id": 1, "question": {"id": 2}, "content": "茶百道欠薪"}},
    ]})
    result = await get_agent("zhihu")().execute(
        AgentRequest(company_name="茶百道"),
        AgentContext(http=FakeHttp({"zhihu.com": payload}), options={"no_browser": True}))
    assert len(result.findings) == 1


async def test_agent_blocked_status_propagates():
    result = await get_agent("weibo")().execute(
        AgentRequest(company_name="茶百道"),
        AgentContext(http=FakeHttp({"weibo.cn": json.dumps({"ok": 0})}),
                     options={"no_browser": True}))
    assert result.status is AgentStatus.BLOCKED


async def test_tianyancha_web_agent_stores_raw_without_summarizing():
    """天眼查按方案要求「不总结，直接存原数据」：不产 Finding，原样进 metrics+库。"""
    search = padded('<a href="/company/4158787537">四川百茶百道实业股份有限公司</a>')
    page = padded(json.dumps({"creditCode": "91510100X", "regStatus": "存续",
                              "name": "四川百茶百道实业股份有限公司"}) + "<div>对外投资10</div>")
    routes = {"/search": search, "/company/4158787537": page,
              "/sifa": padded("<div>2021-01-01 案</div>"),
              "/jingxian": padded("<div>2021-02-01 异常</div>")}
    store = FakeStore()
    result = await get_agent("tianyancha_web")().execute(
        AgentRequest(company_name="四川百茶百道实业股份有限公司"),
        AgentContext(http=FakeHttp(routes), options={"no_browser": True, "store": store}))
    assert result.status in (AgentStatus.OK, AgentStatus.PARTIAL)
    assert result.findings == []                      # 不总结
    assert result.meta["counts"]["对外投资"] == 10
    assert result.meta["profile"]["credit_code"] == "91510100X"
    assert store.raw, "原数据应该落进 backduty_raw"
    assert store.raw[0][1] == "tianyancha_web"
    assert store.raw[0][2]["profile"]["credit_code"] == "91510100X"


async def test_tianyan_ai_agent_exposes_meta():
    result = await get_agent("tianyan_ai")().execute(
        AgentRequest(company_name="茶百道"),
        AgentContext(options={"cli": _cli_ok(), "no_browser": True}))
    assert result.status is AgentStatus.OK
    assert result.meta["registration"]["regStatus"] == "存续"
    assert result.meta["free_tools_only"] is True


async def test_agent_declares_tools():
    for name in ("zhihu", "tieba", "weibo", "tianyancha_web", "tianyan_ai"):
        agent = get_agent(name)()
        assert isinstance(agent, ToolAgent)
        assert agent.tools, f"{name} 没有声明工具"
        for call in agent.tools:
            assert isinstance(call, ToolCall)
            get_tool(call.tool)          # 工具必须存在


# ---------------------------------------------------------------- 强制日志工具
def test_every_agent_has_log_tool():
    """要求：所有 agent 必须含「报错日志写入」工具。"""
    from boss_crawler.agents.registry import catalog

    for row in catalog():
        agent = get_agent(row["name"])()
        assert "log_event" in getattr(agent, "mandatory_tools", ()), row["name"]
        get_tool("log_event")


async def test_log_event_tool_writes_to_store():
    store = FakeStore()
    result = await get_tool("log_event").execute(
        _box(store=store), message="天眼查被限频", level="warn",
        agent="tianyancha_web", status="blocked", code="blocked")
    assert result.status is AgentStatus.OK
    assert store.events and store.events[0]["message"] == "天眼查被限频"
    assert store.events[0]["level"] == "warn"


async def test_log_event_falls_back_to_file(tmp_path):
    result = await get_tool("log_event").execute(
        _box(log_dir=str(tmp_path)), message="无库环境", agent="zhihu")
    assert result.status is AgentStatus.OK
    written = (tmp_path / "agents.jsonl").read_text(encoding="utf-8").strip()
    assert "无库环境" in written


async def test_blocked_agent_auto_writes_diagnostic():
    """agent 被挡时应自动落一条诊断，不用调用方操心。"""
    store = FakeStore()
    result = await get_agent("weibo")().execute(
        AgentRequest(company_name="茶百道"),
        AgentContext(http=FakeHttp({"weibo.cn": json.dumps({"ok": 0, "msg": "请先登录"})}),
                     options={"no_browser": True, "store": store}))
    assert result.status is AgentStatus.BLOCKED
    assert store.events, "被挡时必须写日志"
    assert store.events[0]["status"] == "blocked"
    assert store.events[0]["agent"] == "weibo"


# ---------------------------------------------------------------- 用户询问工具
async def test_ask_user_without_channel_does_not_hang():
    result = await get_tool("ask_user").execute(_box(), question="想强调哪段经历？")
    assert result.status is AgentStatus.EMPTY
    assert any("无交互通道" in note for note in result.notes)


async def test_ask_user_uses_injected_callback():
    answers = []

    async def responder(question, options):
        answers.append(question)
        return "后端高并发那段"

    result = await get_tool("ask_user").execute(
        _box(ask_user=responder), question="想强调哪段经历？")
    assert result.status is AgentStatus.OK
    assert result.data["answer"] == "后端高并发那段"
    assert answers


async def test_ask_user_sync_callback_supported():
    result = await get_tool("ask_user").execute(
        _box(ask_user=lambda q, o: "同步回答"), question="Q")
    assert result.data["answer"] == "同步回答"


async def test_ask_user_empty_answer_is_skipped():
    result = await get_tool("ask_user").execute(
        _box(ask_user=lambda q, o: "   "), question="Q")
    assert result.status is AgentStatus.EMPTY
