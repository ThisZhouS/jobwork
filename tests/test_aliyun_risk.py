"""阿里云云市场风险适配器测试（全部离线）。

没有真实 AppCode，所以用临时配置文件 + 假 http 验证：
配置解析、URL 拼装、响应归一、缺配置/缺 key/超预算的降级行为。
"""
from __future__ import annotations

import json

import pytest

from boss_crawler.agents.base import AgentContext, AgentStatus
from boss_crawler.agents.tools.base import _TOOLS, ToolBox
from boss_crawler.providers import aliyun_market as market


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """写一份指向假域名的配置，并把默认路径指过去。"""
    path = tmp_path / "risk_api.json"
    path.write_text(json.dumps({
        "profiles": {
            "judicial": {
                "enabled": True,
                "base": "https://demo.market.alicloudapi.com",
                "path": "/enterprise/risk",
                "params": {"keyword": "{company}", "page": "1"},
                "items_path": "data.list",
                "fields": {"title": "caseName", "case_no": "caseNo",
                           "court": "court", "date": "judgeTime"},
                "budget": 2,
            },
            "business": {
                "enabled": True,
                "method": "POST",
                "base": "https://demo.market.alicloudapi.com",
                "path": "/api/company_search/query",
                "body": {"keyword": "{company}", "pageNum": "1", "pageSize": "10"},
                "items_path": "data.companyList",
                "fields": {"title": "companyName", "status": "companyStatus"},
                "profile_fields": {"name": "companyName", "reg_status": "companyStatus",
                                   "credit_code": "creditNo"},
                "budget": 2,
            },
            "off": {"enabled": False, "base": "https://x/api", "path": "/p"},
            "nofill": {"enabled": True, "base": "", "path": ""},
        }
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(market, "CONFIG_FILE", path)
    return path


class FakeHttp:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.urls: list[str] = []
        self.headers: list[dict] = []
        self.methods: list[str] = []
        self.bodies: list[dict] = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        self.headers.append(kwargs.get("headers") or {})
        self.methods.append("GET")
        if self.error is not None:
            raise self.error
        return json.dumps(self.payload, ensure_ascii=False)

    async def post(self, url, **kwargs):
        self.urls.append(url)
        self.headers.append(kwargs.get("headers") or {})
        self.methods.append("POST")
        self.bodies.append(kwargs.get("data") or {})
        if self.error is not None:
            raise self.error
        return json.dumps(self.payload, ensure_ascii=False)


def toolbox(http):
    ctx = AgentContext(http=http)
    return ToolBox(ctx, delay=0, retries=0, allow_browser=False)


def tool():
    instance = _TOOLS["aliyun_risk"]
    instance.reset()
    return instance


# ---------------------------------------------------------------- 配置层
def test_load_and_build_url(cfg):
    profiles = market.load()
    assert set(profiles) == {"judicial", "business", "off", "nofill"}
    url = market.build_url(profiles["judicial"], "成都某某公司")
    assert url.startswith("https://demo.market.alicloudapi.com/enterprise/risk?")
    assert "%E6%88%90%E9%83%BD" in url      # 已 urlencode
    assert "page=1" in url


def test_dig_handles_nested_and_missing(cfg):
    payload = {"data": {"list": [{"a": 1}]}}
    assert market.dig(payload, "data.list") == [{"a": 1}]
    assert market.dig(payload, "data.nope.list") is None
    assert market.dig(payload, "") is payload


def test_appcode_read_from_env(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "test-code-123")
    assert market.has_appcode() is True
    assert market.describe()["appcode_source"] == "ALIYUN_APPCODE"


def test_describe_never_leaks_code(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "super-secret-code")
    payload = json.dumps(market.describe(), ensure_ascii=False)
    assert "super-secret-code" not in payload


# ---------------------------------------------------------------- 归一
def test_normalize_maps_fields(cfg):
    profile = market.load()["judicial"]
    payload = {"data": {"list": [
        {"caseName": "买卖合同纠纷", "caseNo": "(2024)川01民初1号",
         "court": "成都中院", "judgeTime": "2024-05-01"},
        {"caseName": "劳动争议"},
    ]}}
    rows = market.normalize(payload, profile)
    assert len(rows) == 2
    assert rows[0]["title"] == "买卖合同纠纷"
    assert rows[0]["case_no"] == "(2024)川01民初1号"
    assert rows[0]["court"] == "成都中院"
    assert rows[0]["raw"]["caseNo"] == "(2024)川01民初1号"
    # 缺字段时留空，不猜
    assert rows[1]["case_no"] is None


def test_normalize_finds_list_without_items_path(cfg):
    profile = market.load()["judicial"]
    profile.items_path = ""
    rows = market.normalize({"code": 0, "result": [{"caseName": "x"}]}, profile)
    assert [r["title"] for r in rows] == ["x"]


# ---------------------------------------------------------------- 工具
async def test_tool_calls_with_appcode_header(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code-abc")
    http = FakeHttp({"data": {"list": [{"caseName": "诉讼", "caseNo": "1"}]}})
    result = await tool().call(toolbox(http), company="成都某某公司")

    assert result.status is AgentStatus.OK
    assert len(result.data) == 1
    assert result.data[0]["title"] == "诉讼"
    assert http.headers[0]["Authorization"] == "APPCODE code-abc"
    assert "keyword=" in http.urls[0]


def test_build_body_replaces_company(cfg):
    profile = market.load()["business"]
    body = market.build_body(profile, "成都某某公司")
    assert body == {"keyword": "成都某某公司", "pageNum": "1", "pageSize": "10"}


async def test_tool_posts_form_body_and_maps_profile(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code-abc")
    http = FakeHttp({"data": {"companyList": [
        {"companyName": "成都某某公司", "companyStatus": "存续",
         "creditNo": "91510100MA00000000"},
        {"companyName": "无关公司", "companyStatus": "在营"},
    ]}})
    result = await tool().call(toolbox(http), company="成都某某公司", profile="business")

    assert result.status is AgentStatus.OK
    assert http.methods == ["POST"]
    assert http.bodies[0]["keyword"] == "成都某某公司"
    assert http.headers[0]["Content-Type"].startswith(
        "application/x-www-form-urlencoded")
    # 模糊搜索返回多家时只保留最匹配的一家
    assert len(result.data) == 1
    assert result.data[0]["title"] == "成都某某公司"
    assert result.data[0]["profile"]["reg_status"] == "存续"
    assert result.data[0]["profile"]["credit_code"] == "91510100MA00000000"


def test_best_match_prefers_exact_and_shorter(cfg):
    profile = market.load()["business"]
    rows = market.normalize({"data": {"companyList": [
        {"companyName": "深圳市本手信息技术有限公司", "companyStatus": "在营"},
        {"companyName": "本手信息", "companyStatus": "存续"},
        {"companyName": "其它公司", "companyStatus": "注销"},
    ]}}, profile)
    best = market.best_match(rows, "本手信息")
    assert best is not None
    assert best["title"] == "本手信息"


async def test_tool_blocked_without_appcode(cfg, monkeypatch):
    monkeypatch.delenv("ALIYUN_APPCODE", raising=False)
    monkeypatch.setattr(market, "STATE_FILE", cfg.parent / "none.txt")
    result = await tool().call(toolbox(FakeHttp({})), company="某公司")
    assert result.status is AgentStatus.BLOCKED
    assert "AppCode" in (result.error or "")


async def test_tool_blocked_when_profile_disabled(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code")
    result = await tool().call(toolbox(FakeHttp({})), company="某公司", profile="off")
    assert result.status is AgentStatus.BLOCKED
    assert "未启用" in (result.error or "")


async def test_tool_blocked_when_profile_not_filled(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code")
    result = await tool().call(toolbox(FakeHttp({})), company="某公司", profile="nofill")
    assert result.status is AgentStatus.BLOCKED
    assert "base/path" in (result.error or "")


async def test_tool_unknown_profile(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code")
    result = await tool().call(toolbox(FakeHttp({})), company="某公司", profile="nope")
    assert result.status is AgentStatus.BLOCKED


async def test_budget_guard_stops_extra_calls(cfg, monkeypatch):
    """预算 2 次：第 3 次调用不再发请求。"""
    monkeypatch.setenv("ALIYUN_APPCODE", "code")
    http = FakeHttp({"data": {"list": [{"caseName": "x"}]}})
    instance = tool()
    box = toolbox(http)
    for _ in range(2):
        assert (await instance.call(box, company="某公司")).status is AgentStatus.OK
    third = await instance.call(box, company="某公司")
    assert third.status is AgentStatus.FAILED
    assert "预算" in (third.error or "")
    assert len(http.urls) == 2          # 第三次真的没发


async def test_tool_network_error_degrades(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code")
    result = await tool().call(toolbox(FakeHttp(error=RuntimeError("超时"))), company="某公司")
    assert result.status is AgentStatus.FAILED
    assert "超时" in (result.error or "")


async def test_tool_auth_error_is_blocked(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "not-an-appcode")
    result = await tool().call(
        toolbox(FakeHttp(error=RuntimeError("401 Unauthorized"))), company="某公司")
    assert result.status is AgentStatus.BLOCKED
    assert "AppCode" in (result.error or "")


async def test_tool_empty_rows_explains_not_safe(cfg, monkeypatch):
    monkeypatch.setenv("ALIYUN_APPCODE", "code")
    result = await tool().call(toolbox(FakeHttp({"data": {"list": []}})), company="某公司")
    assert result.status is AgentStatus.EMPTY
    assert result.notes
