"""天眼查 spider 与落库管道的离线测试（假 transport + 假数据库）。

验证三件事：请求链路是否按预期展开、关系分级与预算是否生效、风险是否
按公司聚合后整批落库。
"""
from __future__ import annotations

import json

import pytest

from boss_crawler.engine import Downloader, Engine, Item, Settings
from boss_crawler.providers.tyc_pipelines import (
    ProfilePipeline,
    RelationPipeline,
    RiskBufferPipeline,
    SkipLogPipeline,
)
from boss_crawler.providers.tyc_spider import TianyanchaSpider

SEARCH_HIT = {
    "error_code": 0,
    "result": {
        "total": 1,
        "items": [{"id": 22822, "name": "北京百度网讯科技有限公司", "creditCode": "91110000802100433B"}],
    },
}

IC_PAYLOAD = {
    "error_code": 0,
    "result": {
        "id": 22822,
        "name": "北京百度网讯科技有限公司",
        "creditCode": "91110000802100433B",
        "legalPersonName": "梁志祥",
        "regStatus": "存续",
        "regCapital": "1342128万人民币",
        "headquarters": {"id": 9, "name": "百度控股有限公司", "reg_status": "存续"},
        "investList": [
            {"id": 1, "name": "全资子公司", "percent": "100%"},
            {"id": 2, "name": "参股公司", "percent": "25%"},
            {"id": 3, "name": "小额投资", "percent": "5%"},
        ],
        "branchList": [{"id": 4, "name": "上海分公司"}],
        "abnormalList": [{"putReason": "未公示年报", "putDate": "2020-01-01", "putDepartment": "市监局"}],
        "illegalList": [],
        "punishList": [{"punishNumber": "P1", "reason": "广告违法", "decisionDate": "2021-01-01",
                        "departmentName": "市监局"}],
    },
}

DISHONEST_HIT = {"error_code": 0, "result": {"total": 1, "items": [
    {"courtname": "某法院", "regdate": "2022-01-01", "duty": "偿还欠款"}
]}}
ZHIXING_EMPTY = {"error_code": 0, "result": {"total": 0, "items": []}}


class RouterTransport:
    """按 URL 片段路由到不同假响应，并统计每个接口被调用几次。"""

    def __init__(self, *, search=None, ic=None, dishonest=None, zhixing=None):
        self.routes = {
            "search": search if search is not None else (200, json.dumps(SEARCH_HIT)),
            "cb/ic": ic if ic is not None else (200, json.dumps(IC_PAYLOAD)),
            "dishonest": dishonest if dishonest is not None else (200, json.dumps(DISHONEST_HIT)),
            "zhixinginfo": zhixing if zhixing is not None else (200, json.dumps(ZHIXING_EMPTY)),
        }
        self.calls: list[tuple[str, str]] = []

    async def fetch(self, url, params, headers, timeout):
        for name, payload in self.routes.items():
            if name in url:
                self.calls.append((name, str(params.get("keyword"))))
                status, body = payload
                return status, body, 1
        return 404, "{}", 1

    async def close(self):
        return None

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)


class FakeDB:
    """记录写入调用的假库，字段语义与真库一致。"""

    def __init__(self):
        self.profiles: dict[str, dict] = {}
        self.relations: dict[str, list] = {}
        self.risks: dict[str, list] = {}
        self.committed = 0

    def save_tyc_profile(self, key, profile, *, match_score, match_note, raw):
        self.profiles[key] = {"profile": profile, "score": match_score, "note": match_note}

    def replace_tyc_relations(self, key, rows):
        self.relations[key] = rows
        return len(rows)

    def replace_tyc_risks(self, key, rows):
        self.risks[key] = rows
        return len(rows)

    def commit(self):
        self.committed += 1


def _pipelines(db):
    return [
        ProfilePipeline(db),
        RelationPipeline(db),
        RiskBufferPipeline(db),
        SkipLogPipeline(db),
    ]


def _engine(spider, transport, db, *, settings=None):
    s = settings or Settings({"CONCURRENT_REQUESTS": 2, "DOWNLOAD_DELAY": 0, "RETRY_BACKOFF_BASE": 0.01})
    return Engine(
        spider,
        settings=s,
        downloader=Downloader(s, transport=transport),
        pipelines=_pipelines(db),
    )


COMPANY = [{"company_key": "baidu", "company_name": "百度", "legal_name": "北京百度网讯科技有限公司"}]


async def test_spider_writes_profile_relations_and_risks():
    transport = RouterTransport()
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t", min_percent=20, max_related=2, max_cost=100)
    await _engine(spider, transport, db).run()

    assert db.profiles["baidu"]["profile"]["name"] == "北京百度网讯科技有限公司"
    kinds = {r["relation"] for r in db.relations["baidu"]}
    assert kinds == {"parent", "subsidiary", "branch"}

    # 5% 的小额投资不该被当成子公司
    subs = [r["to_name"] for r in db.relations["baidu"] if r["relation"] == "subsidiary"]
    assert "全资子公司" in subs and "参股公司" in subs
    assert "小额投资" not in subs

    relations = {(r["relation"], r["risk_type"]) for r in db.risks["baidu"]}
    assert ("self", "abnormal") in relations      # 1001 自带
    assert ("self", "punish") in relations        # 1001 自带
    assert ("self", "dishonest") in relations     # 843
    assert ("parent", "dishonest") in relations   # 关联方
    assert ("subsidiary", "dishonest") in relations


async def test_spider_request_graph_shape():
    transport = RouterTransport()
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t", min_percent=20, max_related=2, max_cost=100)
    await _engine(spider, transport, db).run()

    assert transport.count("search") == 1
    assert transport.count("cb/ic") == 1
    # 自身 1 个实体 + 最多 2 个关联方（母公司、控股子公司）= 3 个实体
    assert transport.count("dishonest") == 3
    assert transport.count("zhixinginfo") == 3


async def test_spider_filters_low_percent_subsidiaries():
    transport = RouterTransport()
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t", min_percent=50, max_related=5, max_cost=100)
    await _engine(spider, transport, db).run()
    subs = [r["to_name"] for r in db.relations["baidu"] if r["relation"] == "subsidiary"]
    assert subs == ["全资子公司"]          # 25% 被 50% 阈值挡掉


async def test_spider_skip_risks_does_not_call_risk_apis():
    transport = RouterTransport()
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t", skip_risks=True)
    await _engine(spider, transport, db).run()
    assert transport.count("dishonest") == 0
    assert transport.count("zhixinginfo") == 0
    # 但 1001 自带的风险仍应落库
    assert any(r["risk_type"] == "punish" for r in db.risks["baidu"])


async def test_spider_only_relations_skips_related_entities():
    transport = RouterTransport()
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t", only_relations=True, max_related=3)
    await _engine(spider, transport, db).run()
    assert db.relations["baidu"]
    # 只查自身两个风险接口
    assert transport.count("dishonest") == 1
    assert transport.count("zhixinginfo") == 1


async def test_spider_handles_no_match():
    empty = {"error_code": 0, "result": {"total": 0, "items": []}}
    transport = RouterTransport(search=(200, json.dumps(empty)))
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t")
    await _engine(spider, transport, db).run()
    assert db.profiles == {}
    assert transport.count("cb/ic") == 0


async def test_spider_does_not_retry_bad_token():
    body = json.dumps({"error_code": 300009, "reason": "账号信息有误"})
    transport = RouterTransport(search=(200, body))
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="bad")
    stats = await _engine(spider, transport, db).run()
    # 鉴权错误不重试，只调用一次
    assert transport.count("search") == 1
    assert stats["request_retried"] == 0


async def test_spider_retries_transient_business_error():
    throttled = json.dumps({"error_code": 300005, "reason": "触发限流"})
    transport = RouterTransport(ic=(200, throttled))
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t")
    stats = await _engine(spider, transport, db).run()
    assert stats["request_retried"] >= 1
    assert transport.count("cb/ic") > 1


async def test_spider_cost_is_tracked():
    transport = RouterTransport()
    db = FakeDB()
    spider = TianyanchaSpider(COMPANY, token="t", max_related=2, max_cost=100)
    await _engine(spider, transport, db).run()
    # search 0.01 + ic 1.00 + 6 个风险接口（自身+2关联方，各 2 个接口）× 0.15
    assert spider.spent == pytest.approx(0.01 + 1.00 + 6 * 0.15)
    assert spider.cost_by_api["ic"] == pytest.approx(1.0)
    assert spider.cost_by_api["dishonest"] == pytest.approx(3 * 0.15)


async def test_spider_rejects_missing_token():
    from boss_crawler.providers.tianyancha import TianyanchaError

    spider = TianyanchaSpider(COMPANY, token="")
    with pytest.raises(TianyanchaError, match="缺少天眼查 token"):
        await _engine(spider, RouterTransport(), FakeDB()).run()


async def test_risk_buffer_flushes_even_without_rows():
    """没有风险也要落一次空列表，才能清掉上一轮的旧数据。"""
    db = FakeDB()
    buffer = RiskBufferPipeline(db)
    await buffer.process_item(Item("company_risk_watch", related_key="k1"))
    await buffer.flush()
    assert db.risks["k1"] == []


async def test_risk_buffer_groups_by_company():
    db = FakeDB()
    buffer = RiskBufferPipeline(db)
    await buffer.process_item(Item("company_risk_watch", related_key="a"))
    await buffer.process_item(Item("company_risk_watch", related_key="b"))
    await buffer.process_item(Item("company_risk", related_key="a", rows=[{"risk_type": "dishonest"}]))
    await buffer.process_item(Item("company_risk", related_key="a", rows=[{"risk_type": "punish"}]))
    await buffer.process_item(Item("company_risk", related_key="b", rows=[{"risk_type": "zhixing"}]))
    await buffer.flush()
    assert len(db.risks["a"]) == 2
    assert len(db.risks["b"]) == 1


async def test_skip_pipeline_collects_skipped_companies():
    db = FakeDB()
    pipeline = SkipLogPipeline(db)
    await pipeline.process_item(Item("company_skipped", company_key="x", company_name="某公司", note="无匹配"))
    assert pipeline.skipped == [{"company_key": "x", "note": "无匹配"}]
