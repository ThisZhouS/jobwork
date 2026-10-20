"""天眼查背调的离线测试：全部基于录制的返回样例，不联网、不花接口费。"""
from __future__ import annotations

import json

import pytest

from boss_crawler import config
from boss_crawler.providers import (
    DueDiligenceOptions,
    classify_invest,
    estimate_cost,
    investigate,
    name_score,
    parse_dishonest,
    parse_profile,
    parse_relations,
    parse_risks,
    parse_zhixing,
    pick_best,
    risk_summary,
    to_percent,
    verdict,
)
from boss_crawler.providers.tianyancha import TianyanchaClient, TianyanchaError

# ---------------------------------------------------------------- 录制样例
IC_RESULT = {
    "id": 22822,
    "name": "北京百度网讯科技有限公司",
    "creditCode": "91110000802100433B",
    "legalPersonName": "梁志祥",
    "regStatus": "存续",
    "regCapital": "1342128万人民币",
    "estiblishTime": "2001-06-05",
    "regLocation": "北京市海淀区上地十街10号",
    "industry": "软件和信息技术服务业",
    "businessScope": "互联网信息服务",
    "phoneNumber": "010-59928888",
    "email": "service@baidu.com",
    "website": "www.baidu.com",
    "staffNum": 30000,
    "headquarters": {
        "id": 300001,
        "name": "百度控股有限公司",
        "reg_status": "存续",
        "legalPersonName": "李彦宏",
        "reg_capital": "10000万人民币",
    },
    "investList": [
        {"id": 1, "name": "百度全资子公司", "percent": "100%", "creditCode": "A1", "regStatus": "存续"},
        {"id": 2, "name": "百度控股子公司", "percent": "60%", "creditCode": "A2", "regStatus": "存续"},
        {"id": 3, "name": "百度参股公司", "percent": "25%", "creditCode": "A3", "regStatus": "存续"},
        {"id": 4, "name": "小额财务投资", "percent": "5%", "creditCode": "A4", "regStatus": "存续"},
    ],
    "branchList": [{"id": 5, "name": "北京百度网讯科技有限公司上海分公司", "regStatus": "存续"}],
    "abnormalList": [
        {"putReason": "未按规定公示年报", "putDate": "2020-01-01", "putDepartment": "市监局",
         "removeDate": "2020-03-01", "removeReason": "已补报"},
    ],
    "illegalList": [],
    "punishList": [
        {"punishNumber": "X1", "reason": "广告违法", "decisionDate": "2021-05-01",
         "departmentName": "市场监管局"},
    ],
    "staffList": [{"name": "梁志祥", "typeJoin": ["董事长"]}],
}

DISHONEST_RESULT = {
    "total": 1,
    "items": [
        {"casecode": "C1", "courtname": "某法院", "regdate": "2022-01-01",
         "duty": "偿还欠款", "performance": "全部未履行", "disrupttypename": "有履行能力而拒不履行"},
    ],
}

ZHIXING_RESULT = {
    "total": 2,
    "items": [
        {"caseCode": "Z1", "execCourtName": "某法院", "execMoney": "100000", "caseCreateTime": "2022-02-02"},
        {"caseCode": "Z2", "execCourtName": "某法院", "execMoney": "200000", "caseCreateTime": "2022-03-03"},
    ],
}

SEARCH_RESULT = {
    "total": 2,
    "items": [
        {"id": 999, "name": "成都某某网络科技有限公司", "creditCode": "BAD"},
        {"id": 22822, "name": "北京百度网讯科技有限公司", "creditCode": "91110000802100433B"},
    ],
}


# ---------------------------------------------------------------- 纯函数
@pytest.mark.parametrize(
    "raw, expected",
    [("100%", 100.0), ("51.5%", 51.5), (33, 33.0), (None, None), ("未披露", None)],
)
def test_to_percent(raw, expected):
    assert to_percent(raw) == expected


@pytest.mark.parametrize(
    "percent, grade",
    [(100.0, "全资子公司"), (60.0, "控股子公司"), (25.0, "参股公司"), (5.0, "财务投资"), (None, "参与投资(比例未知)")],
)
def test_classify_invest(percent, grade):
    assert classify_invest(percent) == grade


def test_name_score_exact_and_shortname():
    assert name_score("北京百度网讯科技有限公司", "北京百度网讯科技有限公司") == 1.0
    # 简称包含于全称：包含关系是强信号，落在 0.75~1.0
    short = name_score("百度网讯", "北京百度网讯科技有限公司")
    assert 0.75 <= short < 1.0
    # 完全不相干的名字分数应当明显更低
    assert name_score("完全不相干", "北京百度网讯科技有限公司") < 0.6


def test_name_score_handles_empty():
    assert name_score("", "x") == 0.0
    assert name_score("x", "") == 0.0


def test_pick_best_prefers_closest_name():
    best, score = pick_best("北京百度网讯科技有限公司", SEARCH_RESULT["items"])
    assert best is not None and best["id"] == 22822 and score == 1.0


def test_parse_profile_extracts_fields():
    profile = parse_profile(IC_RESULT)
    assert profile["tyc_id"] == 22822
    assert profile["credit_code"] == "91110000802100433B"
    assert profile["legal_person"] == "梁志祥"
    assert profile["phone"] == "010-59928888"
    assert profile["staff_num"] == 30000


def test_parse_relations_both_directions():
    rows = parse_relations(IC_RESULT, from_key="k1")
    kinds = [r["relation"] for r in rows]
    assert kinds.count("parent") == 1
    assert kinds.count("subsidiary") == 4
    assert kinds.count("branch") == 1

    parent = next(r for r in rows if r["relation"] == "parent")
    assert parent["to_name"] == "百度控股有限公司"

    grades = {r["to_name"]: r["grade"] for r in rows if r["relation"] == "subsidiary"}
    assert grades["百度全资子公司"] == "全资子公司"
    assert grades["百度控股子公司"] == "控股子公司"
    assert grades["百度参股公司"] == "参股公司"
    assert grades["小额财务投资"] == "财务投资"


def test_parse_relations_without_parent():
    data = {"id": 1, "name": "独立公司", "headquarters": None, "investList": [], "branchList": []}
    assert parse_relations(data, from_key="k") == []


def test_parse_risks_three_types():
    rows = parse_risks(IC_RESULT, entity_key="e1", entity_name="百度网讯")
    types = [r["risk_type"] for r in rows]
    assert types.count("abnormal") == 1
    assert types.count("punish") == 1
    assert "illegal" not in types
    assert all(r["entity_key"] == "e1" for r in rows)


def test_parse_dishonest_and_zhixing():
    bad = parse_dishonest(DISHONEST_RESULT, entity_key="e1", entity_name="X")
    assert len(bad) == 1 and bad[0]["risk_type"] == "dishonest"
    assert bad[0]["department"] == "某法院"

    zx = parse_zhixing(ZHIXING_RESULT, entity_key="e1", entity_name="X")
    assert len(zx) == 2 and all(r["risk_type"] == "zhixing" for r in zx)


def test_risk_summary_and_verdict():
    rows = parse_risks(IC_RESULT, entity_key="e", entity_name="n")
    summary = risk_summary(rows)
    assert summary == {"abnormal": 1, "punish": 1}
    assert verdict(summary) == "警惕：严重违法或经营异常"
    assert verdict({"dishonest": 1}) == "高危：有失信/被执行记录"
    assert verdict({"zhixing": 2}) == "高危：有失信/被执行记录"
    assert verdict({"punish": 1}) == "关注：有行政处罚"
    assert verdict({}) == "暂未发现明显风险"


def test_estimate_cost_is_linear_and_sane():
    one = estimate_cost(1, depth=1, max_related=3)
    assert one["per_company"] == pytest.approx(1.31)
    assert one["total"] == pytest.approx(1.31 + 3 * 0.30)
    # 关联方越少越便宜
    assert estimate_cost(10, max_related=0)["total"] < estimate_cost(10, max_related=3)["total"]
    # depth=0 时不查关联方
    assert estimate_cost(10, depth=0, max_related=3)["total"] == pytest.approx(10 * 1.31)


# ---------------------------------------------------------------- 客户端
class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _FakeSession:
    """按 api 路径返回录制数据，并记录调用次数。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        for path, payload in self.mapping.items():
            if url.endswith(path):
                return _FakeResponse(payload)
        return _FakeResponse({"error_code": 404, "reason": "no such api"})


def _client(mapping):
    """按 ``config.TYC_API`` 里的真实路径建假 session，避免测试里写死路径。"""
    resolved = {config.TYC_API[name]: payload for name, payload in mapping.items()}
    session = _FakeSession(resolved)
    client = TianyanchaClient(token="test-token", session=session, delay=0, retries=1)
    return client, session


def test_client_requires_token():
    client = TianyanchaClient(token="", delay=0)
    with pytest.raises(TianyanchaError, match="缺少天眼查 token"):
        client.get("search", {"word": "x"})


def test_client_sends_authorization_header():
    client, session = _client({"search": {"error_code": 0, "result": SEARCH_RESULT}})
    client.search("百度")
    assert session.calls[0]["headers"]["Authorization"] == "test-token"


def test_client_returns_result_and_tracks_cost():
    client, _ = _client({"search": {"error_code": 0, "result": SEARCH_RESULT}})
    result = client.search("百度")
    assert result["total"] == 2
    assert client.spent == pytest.approx(0.01)
    assert client.calls[0]["code"] == 0


def test_client_raises_on_permission_error_without_retry():
    client, session = _client({"ic": {"error_code": 300003, "reason": "余额不足"}})
    with pytest.raises(TianyanchaError, match="余额不足"):
        client.ic("x")
    assert len(session.calls) == 1


def test_client_does_not_retry_on_bad_token():
    """实测 300009 = 账号信息有误：重试没意义，且要提示去查 token。"""
    client, session = _client({"search": {"error_code": 300009, "reason": "账号信息有误"}})
    client.retries = 5
    with pytest.raises(TianyanchaError, match="TIANYANCHA_TOKEN"):
        client.search("百度")
    assert len(session.calls) == 1


def test_client_hints_topup_on_insufficient_balance():
    client, _ = _client({"ic": {"error_code": 300003, "reason": "余额不足"}})
    with pytest.raises(TianyanchaError, match="充值"):
        client.ic("x")


def test_client_retries_then_fails():
    client, session = _client({"ic": {"error_code": 500, "reason": "server"}})
    client.retries = 3
    with pytest.raises(TianyanchaError):
        client.ic("x")
    assert len(session.calls) == 3


# ---------------------------------------------------------------- 编排（写库用假对象）
class _FakeDB:
    def __init__(self):
        self.profiles = {}
        self.relations = {}
        self.risks = {}
        self.logs = []

    def save_tyc_profile(self, key, profile, *, match_score, match_note, raw):
        self.profiles[key] = {"profile": profile, "score": match_score, "raw": raw}

    def replace_tyc_relations(self, key, rows):
        self.relations[key] = rows
        return len(rows)

    def replace_tyc_risks(self, key, rows):
        self.risks[key] = rows
        return len(rows)

    def log_tyc_call(self, key, call):
        self.logs.append((key, call))


def _full_mapping():
    """按 api 名（config.TYC_API 的键）给录制数据。"""
    return {
        "search": {"error_code": 0, "result": SEARCH_RESULT},
        "ic": {"error_code": 0, "result": IC_RESULT},
        "dishonest": {"error_code": 0, "result": DISHONEST_RESULT},
        "zhixing": {"error_code": 0, "result": ZHIXING_RESULT},
        "parent": {"error_code": 0, "result": {"name": "兜底母公司", "id": 7}},
    }


def test_investigate_writes_profile_relations_and_risks():
    client, _ = _client(_full_mapping())
    db = _FakeDB()
    targets = [{"company_key": "k1", "company_name": "北京百度网讯科技有限公司"}]

    results = investigate(db, targets, client=client, options=DueDiligenceOptions(max_related=2))

    assert len(results) == 1
    assert results[0].matched and results[0].credit_code == "91110000802100433B"
    assert "k1" in db.profiles
    # 5% 的财务投资被 min_percent=20 过滤掉
    subs = [r for r in db.relations["k1"] if r["relation"] == "subsidiary"]
    assert len(subs) == 3
    assert all((r["percent"] or 0) >= 20 for r in subs)
    # 自身风险 = 3 类清单(1 abnormal + 1 punish) + 失信 1 + 被执行 2
    self_risks = [r for r in db.risks["k1"] if r["relation"] == "self"]
    assert len(self_risks) == 5
    # 关联方风险挂在 parent/subsidiary 上
    assert any(r["relation"] == "parent" for r in db.risks["k1"])
    summary = risk_summary(db.risks["k1"])
    assert summary["dishonest"] >= 1


def test_investigate_respects_max_cost():
    client, _ = _client(_full_mapping())
    db = _FakeDB()
    targets = [
        {"company_key": "k1", "company_name": "北京百度网讯科技有限公司"},
        {"company_key": "k2", "company_name": "北京百度网讯科技有限公司"},
    ]
    options = DueDiligenceOptions(max_cost=0.0)
    results = investigate(db, targets, client=client, options=options)
    assert all(not r.matched for r in results)
    assert all("预算上限" in r.note for r in results)
    assert db.profiles == {}


def test_investigate_skips_unmatched_name():
    client, _ = _client({"search": {"error_code": 0, "result": {"total": 0, "items": []}}})
    db = _FakeDB()
    results = investigate(db, [{"company_key": "k", "company_name": "某大型不明公司"}], client=client)
    assert len(results) == 1 and not results[0].matched
    assert "无匹配" in results[0].note


def test_investigate_prefers_legal_name():
    client, session = _client(_full_mapping())
    db = _FakeDB()
    targets = [{"company_key": "k", "company_name": "百度", "legal_name": "北京百度网讯科技有限公司"}]
    investigate(db, targets, client=client, options=DueDiligenceOptions(max_related=0))
    search_call = next(c for c in session.calls if c["url"].endswith("/search/2.0"))
    assert search_call["params"]["word"] == "北京百度网讯科技有限公司"


def test_investigate_falls_back_to_parent_api():
    mapping = _full_mapping()
    # 去掉 1001 里的 headquarters，逼出 963 兜底
    mapping["ic"] = {
        "error_code": 0,
        "result": {k: v for k, v in IC_RESULT.items() if k != "headquarters"},
    }
    client, _ = _client(mapping)
    db = _FakeDB()
    investigate(db, [{"company_key": "k", "company_name": "北京百度网讯科技有限公司"}],
                client=client, options=DueDiligenceOptions(max_related=0, skip_risks=True))
    parents = [r for r in db.relations["k"] if r["relation"] == "parent"]
    assert parents and parents[0]["to_name"] == "兜底母公司"


def test_investigate_survives_risk_api_failure():
    mapping = _full_mapping()
    mapping["dishonest"] = {"error_code": 300003, "reason": "余额不足"}
    client, _ = _client(mapping)
    db = _FakeDB()
    results = investigate(db, [{"company_key": "k", "company_name": "北京百度网讯科技有限公司"}],
                          client=client, options=DueDiligenceOptions(max_related=0))
    # 失信接口失败不该让整家公司的背调崩掉
    assert results[0].matched
    assert "dishonest" not in risk_summary(db.risks["k"])
    assert "zhixing" in risk_summary(db.risks["k"])


def test_investigate_skip_risks_option():
    client, session = _client(_full_mapping())
    db = _FakeDB()
    investigate(db, [{"company_key": "k", "company_name": "北京百度网讯科技有限公司"}],
                client=client, options=DueDiligenceOptions(skip_risks=True))
    assert db.relations["k"]
    # skip_risks 只跳过额外接口；1001 自带的经营异常/行政处罚不额外花钱，应当保留
    assert set(risk_summary(db.risks["k"])) == {"abnormal", "punish"}
    # 确认没有调用失信/被执行接口
    called = {c["url"] for c in session.calls}
    assert not any("dishonest" in u or "zhixinginfo" in u for u in called)
