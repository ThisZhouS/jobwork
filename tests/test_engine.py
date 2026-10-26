"""异步引擎的离线测试：全部用假 transport，不联网。

覆盖引擎承诺的四件事：队列/去重、并发、重试、管道与收尾判定。
"""
from __future__ import annotations

import asyncio
import json


from boss_crawler.engine import (
    Downloader,
    DupeFilter,
    Engine,
    Item,
    ItemPipeline,
    JsonMiddleware,
    PipelineManager,
    Request,
    Response,
    RetryPolicy,
    Scheduler,
    Settings,
    SignalManager,
    Spider,
    Stats,
)


# ---------------------------------------------------------------- 假 transport
class FakeTransport:
    """按顺序返回预设响应；记录每次调用，便于断言并发与次数。"""

    def __init__(self, script=None, delays=None):
        self.script = list(script or [])
        self.delays = list(delays or [])
        self.calls: list[tuple[str, dict]] = []
        self.active = 0
        self.max_active = 0
        self._index = 0

    async def fetch(self, url, params, headers, timeout):
        self.calls.append((url, dict(params)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            delay = self.delays[self._index] if self._index < len(self.delays) else 0
            if delay:
                await asyncio.sleep(delay)
            step = self.script[self._index] if self._index < len(self.script) else (200, '{"error_code":0}', 1)
            self._index += 1
            return step
        finally:
            self.active -= 1

    async def close(self):
        return None


def _engine(spider, *, settings=None, transport=None, pipelines=None, signals=None):
    s = settings or Settings({"CONCURRENT_REQUESTS": 3, "DOWNLOAD_DELAY": 0, "RETRY_BACKOFF_BASE": 0.01})
    return Engine(
        spider,
        settings=s,
        downloader=Downloader(s, transport=transport or FakeTransport()),
        pipelines=pipelines,
        signals=signals,
    )


class Collect(ItemPipeline):
    def __init__(self):
        self.items: list[Item] = []

    async def process_item(self, item):
        self.items.append(item)
        return item


class LoopSpider(Spider):
    name = "loop"

    def __init__(self, count=5, **kwargs):
        super().__init__(**kwargs)
        self.count = count

    async def start_requests(self):
        for i in range(self.count):
            yield Request(url="https://x/api", params={"i": i}, meta={"i": i}, callback="parse")

    async def parse(self, response):
        yield Item("hit", i=response.meta["i"])


# ---------------------------------------------------------------- 队列与去重
async def test_scheduler_dedups_by_fingerprint():
    scheduler = Scheduler()
    request = Request(url="https://x/a", params={"k": 1})
    assert await scheduler.enqueue(request) is True
    assert await scheduler.enqueue(request) is False
    assert scheduler.dropped == 1
    assert scheduler.enqueued == 1


async def test_scheduler_dont_filter_allows_repeat():
    scheduler = Scheduler()
    request = Request(url="https://x/a", params={"k": 1}, dont_filter=True)
    assert await scheduler.enqueue(request) is True
    assert await scheduler.enqueue(request.with_retry()) is True


async def test_scheduler_priority_order():
    scheduler = Scheduler()
    await scheduler.enqueue(Request(url="https://x/a", meta={"tag": "low"}, priority=1))
    await scheduler.enqueue(Request(url="https://x/b", meta={"tag": "high"}, priority=9))
    first = await scheduler.next_request()
    assert first is not None and first.meta["tag"] == "high"


async def test_scheduler_close_wakes_all_workers():
    scheduler = Scheduler()
    scheduler.close()

    async def take():
        return await scheduler.next_request()

    results = await asyncio.gather(*(take() for _ in range(4)))
    assert results == [None, None, None, None]


def test_dupefilter_records_only_once():
    f = DupeFilter()
    assert f.seen("abc") is False
    assert f.seen("abc") is True
    assert len(f) == 1


# ---------------------------------------------------------------- 重试策略
def test_retry_policy_http_and_business_codes():
    policy = RetryPolicy(times=2, business_codes=frozenset({300005}), jitter=False)
    assert policy.should_retry(Response(request=Request(url="u"), status=503), attempt=0) is True
    assert policy.should_retry(Response(request=Request(url="u"), status=200, error_code=300005), attempt=0) is True
    assert policy.should_retry(Response(request=Request(url="u"), status=200, error_code=0), attempt=0) is False
    assert policy.should_retry(Response(request=Request(url="u"), status=404), attempt=0) is False
    # 达到上限就停
    assert policy.should_retry(Response(request=Request(url="u"), status=503), attempt=2) is False


def test_retry_policy_backoff_is_exponential_and_capped():
    policy = RetryPolicy(backoff_base=1.0, backoff_max=4.0, jitter=False)
    assert [policy.delay_for(n) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 4.0]


# ---------------------------------------------------------------- 引擎主流程
async def test_engine_runs_all_requests_and_items():
    transport = FakeTransport()
    collector = Collect()
    engine = _engine(LoopSpider(5), transport=transport, pipelines=[collector])
    stats = await engine.run()
    assert stats["request_scheduled"] == 5
    assert stats["response_received"] == 5
    assert stats["item_scraped"] == 5
    assert sorted(i["i"] for i in collector.items) == [0, 1, 2, 3, 4]


async def test_engine_respects_concurrency_limit():
    transport = FakeTransport(delays=[0.05] * 10)
    settings = Settings({"CONCURRENT_REQUESTS": 3, "DOWNLOAD_DELAY": 0})
    engine = _engine(LoopSpider(10), settings=settings, transport=transport)
    await engine.run()
    assert transport.max_active <= 3
    assert transport.max_active >= 2   # 确实并发了，而不是串行


async def test_engine_retries_http_and_business_errors():
    # 503, 503, 业务码, 成功
    script = [
        (503, "busy", 1),
        (503, "busy", 1),
        (200, json.dumps({"error_code": 300005, "reason": "limit"}), 1),
        (200, json.dumps({"error_code": 0, "result": {}}), 1),
    ]
    transport = FakeTransport(script=script)
    collector = Collect()
    settings = Settings({
        "CONCURRENT_REQUESTS": 2, "DOWNLOAD_DELAY": 0,
        "RETRY_BACKOFF_BASE": 0.01, "RETRY_TIMES": 3,
        "RETRY_BUSINESS_CODES": (300005,),
    })
    engine = _engine(LoopSpider(1), settings=settings, transport=transport, pipelines=[collector])
    stats = await engine.run()
    assert stats["request_retried"] == 3
    assert len(transport.calls) == 4
    assert stats["item_scraped"] == 1


async def test_engine_gives_up_after_retry_limit():
    transport = FakeTransport(script=[(503, "busy", 1)] * 10)
    collector = Collect()
    settings = Settings({
        "CONCURRENT_REQUESTS": 1, "DOWNLOAD_DELAY": 0,
        "RETRY_BACKOFF_BASE": 0.01, "RETRY_TIMES": 2,
    })
    engine = _engine(LoopSpider(1), settings=settings, transport=transport, pipelines=[collector])
    stats = await engine.run()
    assert len(transport.calls) == 3          # 首次 + 2 次重试
    assert stats["request_retried"] == 2
    assert collector.items == []               # 失败的响应不产出 item
    assert stats["response_failed"] == 3


async def test_engine_chains_requests():
    class ChainSpider(Spider):
        name = "chain"

        async def start_requests(self):
            yield Request(url="https://x/list", params={"p": 1}, meta={"depth": 0}, callback="parse_list")

        async def parse_list(self, response):
            depth = response.meta["depth"]
            if depth < 2:
                yield Request(url="https://x/list", params={"p": depth + 2}, meta={"depth": depth + 1},
                              callback="parse_list")
            yield Item("page", depth=depth)

    collector = Collect()
    engine = _engine(ChainSpider(), transport=FakeTransport(), pipelines=[collector])
    stats = await engine.run()
    assert stats["request_scheduled"] == 3     # 初始 + 两次链式
    assert sorted(i["depth"] for i in collector.items) == [0, 1, 2]


async def test_engine_pipeline_can_drop_items():
    class Drop(ItemPipeline):
        async def process_item(self, item):
            return None

    engine = _engine(LoopSpider(3), transport=FakeTransport(), pipelines=[Drop()])
    stats = await engine.run()
    assert stats["item_dropped"] == 3
    assert stats["item_scraped"] == 0


async def test_engine_respects_max_items():
    collector = Collect()
    settings = Settings({"CONCURRENT_REQUESTS": 2, "DOWNLOAD_DELAY": 0, "MAX_ITEMS": 2})
    engine = _engine(LoopSpider(10), settings=settings, transport=FakeTransport(), pipelines=[collector])
    stats = await engine.run()
    assert stats["item_scraped"] <= 3   # 并发下可能有 1 条在途


async def test_engine_emits_signals():
    signals = SignalManager()
    seen = {"item": 0, "response": 0, "retried": 0}
    signals.connect("item_scraped", lambda **kw: seen.__setitem__("item", seen["item"] + 1))
    signals.connect("response_received", lambda **kw: seen.__setitem__("response", seen["response"] + 1))
    engine = _engine(LoopSpider(3), transport=FakeTransport(), signals=signals)
    await engine.run()
    assert seen["item"] == 3 and seen["response"] == 3


async def test_engine_closes_when_no_requests():
    engine = _engine(LoopSpider(0), transport=FakeTransport())
    stats = await engine.run()
    assert stats["request_scheduled"] == 0
    assert stats["elapsed_s"] >= 0


# ---------------------------------------------------------------- 组件单测
async def test_json_middleware_extracts_error_code():
    middleware = JsonMiddleware()
    response = Response(request=Request(url="u"), status=200,
                        text=json.dumps({"error_code": 300003, "reason": "余额不足"}))
    out = middleware.process_response(response)
    assert out.error_code == 300003
    assert out.error_reason == "余额不足"
    assert out.ok is False


async def test_json_middleware_survives_bad_json():
    middleware = JsonMiddleware()
    response = Response(request=Request(url="u"), status=200, text="<html>not json</html>")
    out = middleware.process_response(response)
    assert out.payload is None
    assert out.error_code is None


async def test_pipeline_manager_reports_errors_without_crashing():
    class Boom(ItemPipeline):
        async def process_item(self, item):
            raise ValueError("boom")

    stats = Stats()
    manager = PipelineManager([Boom()], stats=stats)
    result = await manager.process(Item("x"))
    assert result is None
    assert stats.get("pipeline_error") == 1


async def test_pipeline_manager_supports_sync_pipeline():
    class SyncPipeline(ItemPipeline):
        def process_item(self, item):
            item["touched"] = True
            return item

    manager = PipelineManager([SyncPipeline()])
    out = await manager.process(Item("x"))
    assert out is not None and out["touched"] is True


def test_settings_override_and_attribute_access():
    s = Settings({"CONCURRENT_REQUESTS": 9})
    assert s.CONCURRENT_REQUESTS == 9
    assert s.get("DOWNLOAD_DELAY") == 0.2
    child = s.copy({"RETRY_TIMES": 7})
    assert child.RETRY_TIMES == 7 and s.RETRY_TIMES == 3


def test_stats_summary_has_standard_keys():
    s = Stats()
    summary = s.summary()
    for key in Stats.STANDARD_KEYS:
        assert key in summary
        assert summary[key] == 0


async def test_signal_errors_do_not_break_engine():
    signals = SignalManager()

    def boom(**kwargs):
        raise RuntimeError("bad handler")

    signals.connect("response_received", boom)
    engine = _engine(LoopSpider(2), transport=FakeTransport(), signals=signals)
    stats = await engine.run()
    assert stats["response_received"] == 2


async def test_engine_emits_gave_up_after_retries_exhausted():
    """重试用尽要发 request_gave_up，否则失败请求对调用方完全不可见。"""
    signals = SignalManager()
    seen: list[dict] = []
    signals.connect("request_gave_up", lambda **kw: seen.append(kw))
    transport = FakeTransport(script=[(503, "busy", 1)] * 10)
    settings = Settings({
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 0,
        "RETRY_BACKOFF_BASE": 0.01,
        "RETRY_TIMES": 1,
    })
    engine = _engine(LoopSpider(1), settings=settings, transport=transport, signals=signals)
    await engine.run()
    assert len(seen) == 1
    assert seen[0]["response"].status == 503
