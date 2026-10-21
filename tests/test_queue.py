"""任务队列与重试策略的测试。"""
from __future__ import annotations

import asyncio

import pytest

from boss_crawler.app.queue import RetryPolicy, TaskQueue


def policy(**kwargs) -> RetryPolicy:
    """测试用的快退避：不抖动、基数极小，跑得快且确定。"""
    base = {"max_attempts": 3, "base_delay": 0.01, "factor": 2.0, "jitter": 0.0}
    base.update(kwargs)
    return RetryPolicy(**base)


# ---------------------------------------------------------------- 基本
async def test_runs_all_tasks():
    queue = TaskQueue(workers=2, timeout=5)
    done: list[str] = []

    async def make(value):
        async def fn():
            await asyncio.sleep(0)
            done.append(value)
            return value
        return fn

    results = await queue.map([(k, await make(k)) for k in "abc"])
    assert sorted(done) == ["a", "b", "c"]
    assert all(r.ok for r in results)
    assert queue.stats["succeeded"] == 3


async def test_result_carries_value_and_attempts():
    queue = TaskQueue(workers=1, timeout=5)

    async def fn():
        return 42

    results = await queue.map([("k", fn)])
    assert results[0].value == 42
    assert results[0].attempts == 1
    assert results[0].as_dict()["ok"] is True


# ---------------------------------------------------------------- 重试
async def test_retries_then_succeeds():
    queue = TaskQueue(workers=1, retry=policy(max_attempts=3), timeout=5)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("暂时失败")
        return "ok"

    results = await queue.map([("k", flaky)])
    assert calls["n"] == 3
    assert results[0].ok is True
    assert results[0].attempts == 3
    assert queue.stats["retried"] == 2


async def test_gives_up_after_max_attempts():
    queue = TaskQueue(workers=1, retry=policy(max_attempts=2), timeout=5)
    calls = {"n": 0}

    async def always_fail():
        calls["n"] += 1
        raise ValueError("坏")

    results = await queue.map([("k", always_fail)])
    assert calls["n"] == 2
    assert results[0].ok is False
    assert "ValueError" in results[0].error
    assert queue.stats["failed"] == 1


async def test_non_retryable_exception_fails_fast():
    queue = TaskQueue(workers=1, retry=policy(max_attempts=5,
                                              retry_on=(ConnectionError,)), timeout=5)
    calls = {"n": 0}

    async def wrong_type():
        calls["n"] += 1
        raise ValueError("不该重试")

    results = await queue.map([("k", wrong_type)])
    assert calls["n"] == 1
    assert results[0].ok is False


async def test_per_task_max_attempts_override():
    queue = TaskQueue(workers=1, retry=policy(max_attempts=5), timeout=5)
    calls = {"n": 0}

    async def fail():
        calls["n"] += 1
        raise RuntimeError("x")

    queue.submit("k", fail, max_attempts=2)
    await queue.run()
    assert calls["n"] == 2


async def test_backoff_delay_grows_and_caps():
    p = RetryPolicy(base_delay=1.0, factor=2.0, max_delay=3.0, jitter=0.0)
    assert p.delay_for(1) == 1.0
    assert p.delay_for(2) == 2.0
    assert p.delay_for(3) == 3.0      # 封顶
    assert p.delay_for(10) == 3.0


async def test_jitter_keeps_delay_in_range():
    p = RetryPolicy(base_delay=1.0, factor=1.0, jitter=0.25)
    samples = [p.delay_for(1) for _ in range(50)]
    assert all(0.75 <= s <= 1.25 for s in samples)
    assert len(set(samples)) > 1      # 确实是抖动的


# ---------------------------------------------------------------- 去重
async def test_duplicate_key_skipped():
    queue = TaskQueue(workers=1, timeout=5)
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1

    assert queue.submit("same", fn) is True
    assert queue.submit("same", fn) is False
    await queue.run()
    assert calls["n"] == 1
    assert queue.stats["duplicate"] == 1


async def test_dedupe_can_be_disabled():
    queue = TaskQueue(workers=1, dedupe=False, timeout=5)
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1

    queue.submit("same", fn)
    queue.submit("same", fn)
    await queue.run()
    assert calls["n"] == 2


# ---------------------------------------------------------------- 并发与优先级
async def test_concurrency_never_exceeds_workers():
    queue = TaskQueue(workers=3, timeout=5)
    state = {"now": 0, "peak": 0}

    async def fn():
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.02)
        state["now"] -= 1

    await queue.map([(f"t{i}", fn) for i in range(9)])
    assert state["peak"] <= 3
    assert state["peak"] >= 2          # 确实并发过，不是串行


async def test_higher_priority_runs_first():
    queue = TaskQueue(workers=1, timeout=5)
    order: list[str] = []

    async def make(name):
        async def fn():
            order.append(name)
        return fn

    queue.submit("low", await make("low"), priority=0)
    queue.submit("high", await make("high"), priority=-5)
    queue.submit("mid", await make("mid"), priority=-1)
    await queue.run()
    assert order == ["high", "mid", "low"]


# ---------------------------------------------------------------- 超时与事件
async def test_timeout_counts_and_fails():
    queue = TaskQueue(workers=1, timeout=0.05,
                      retry=policy(max_attempts=1))
    async def slow():
        await asyncio.sleep(1.0)

    results = await queue.map([("k", slow)])
    assert results[0].ok is False
    assert queue.stats["timed_out"] == 1


async def test_events_emitted():
    events: list[dict] = []
    queue = TaskQueue(workers=1, timeout=5, on_event=events.append)

    async def fn():
        return 1

    await queue.map([("k", fn)])
    assert [e["type"] for e in events] == ["task_done"]


async def test_broken_event_sink_does_not_break_queue():
    def boom(_event):
        raise RuntimeError("日志坏了")

    queue = TaskQueue(workers=1, timeout=5, on_event=boom)

    async def fn():
        return 1

    results = await queue.map([("k", fn)])
    assert results[0].ok is True


async def test_summary_shape():
    queue = TaskQueue(workers=2, timeout=5)
    await queue.map([("k", lambda: asyncio.sleep(0))])
    summary = queue.summary()
    assert summary["workers"] == 2
    assert summary["succeeded"] == 1
    assert "retried" in summary


async def test_empty_queue_runs_immediately():
    queue = TaskQueue(workers=2, timeout=5)
    assert await queue.run() == []
