"""任务队列 + 重试（对标 Scrapy 的 scheduler / retry middleware）。

为什么业务流水线需要它：原来「公司 × 平台」是两层 ``for`` 顺序跑，
4 个平台就是 4 倍的墙钟时间，而且任何一个平台被限流就整段卡住。
Scrapy 的做法是把请求丢进调度器、由并发数控制同时跑几个、失败按退避策略重排，
这里把同一套东西用在 agent 任务上。

保留的三个 Scrapy 特性：

1. **优先级**：小的先出（评分可以先于全量背调跑起来）；
2. **去重**：同一个 key 在排队/执行中不重复入队（``dont_filter`` 可关）；
3. **退避重试**：指数退避 + 抖动，避免被限流时整齐地重试（那等于自己打自己）。

刻意不做的事：不引入 Celery/Redis。这个项目是单进程本地工具，
加外部 broker 只会让"跑起来"变复杂。
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

#: 任务工厂：返回一个协程
TaskFn = Callable[[], Awaitable[Any]]


@dataclass
class RetryPolicy:
    """退避策略：``base * factor ** (attempt-1)``，再乘一个抖动系数。"""

    max_attempts: int = 3
    base_delay: float = 0.4
    factor: float = 2.0
    max_delay: float = 8.0
    jitter: float = 0.25
    #: 只有这些异常会重试；其余直接算失败（比如参数错误重试也没用）
    retry_on: tuple[type[BaseException], ...] = (Exception,)

    def delay_for(self, attempt: int) -> float:
        raw = self.base_delay * (self.factor ** max(0, attempt - 1))
        raw = min(raw, self.max_delay)
        if self.jitter:
            raw *= 1 + random.uniform(-self.jitter, self.jitter)
        return max(0.0, raw)

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        return attempt < self.max_attempts and isinstance(exc, self.retry_on)


@dataclass
class TaskResult:
    key: str
    ok: bool
    value: Any = None
    error: str | None = None
    attempts: int = 1
    elapsed: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "ok": self.ok, "error": self.error,
                "attempts": self.attempts, "elapsed": round(self.elapsed, 3)}


@dataclass(order=True)
class _Item:
    """堆元素。``order=True`` 会按字段顺序比较，所以 ready 放最前。"""

    ready_at: float
    priority: int
    seq: int
    key: str = field(compare=False)
    fn: TaskFn = field(compare=False)
    #: 已经尝试过几次（0 表示还没跑）
    attempts: int = field(default=0, compare=False)
    #: 该任务的重试上限；None 表示用队列的默认策略
    max_attempts: int | None = field(default=None, compare=False)


class TaskQueue:
    """并发执行一组异步任务，失败按策略重试。

    用法::

        queue = TaskQueue(workers=4, retry=RetryPolicy(max_attempts=3))
        await queue.submit("zhihu:/公司A", lambda: agent.execute(req, ctx))
        results = await queue.run()

    ``submit`` 只是入队，``run`` 才真正开跑——这样调用方能先把整批任务攒好。
    """

    def __init__(
        self,
        *,
        workers: int = 4,
        retry: RetryPolicy | None = None,
        timeout: float | None = 120.0,
        dedupe: bool = True,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.workers = max(1, int(workers))
        self.retry = retry or RetryPolicy()
        self.timeout = timeout
        self.dedupe = dedupe
        self._on_event = on_event
        self._heap: list[_Item] = []
        self._seq = itertools.count()
        self._seen: set[str] = set()
        self._running: set[asyncio.Task] = set()
        self._results: list[TaskResult] = []
        self.stats: dict[str, int] = {
            "submitted": 0, "succeeded": 0, "failed": 0,
            "retried": 0, "duplicate": 0, "timed_out": 0,
        }

    # ------------------------------------------------------------ 入队
    def submit(
        self,
        key: str,
        fn: TaskFn,
        *,
        priority: int = 0,
        max_attempts: int | None = None,
        dedupe: bool | None = None,
    ) -> bool:
        """入队一个任务。返回是否真的入队（去重命中时返回 False）。"""
        if dedupe if dedupe is not None else self.dedupe:
            if key in self._seen:
                self.stats["duplicate"] += 1
                return False
        self._seen.add(key)
        item = _Item(ready_at=0.0, priority=priority, seq=next(self._seq),
                     key=key, fn=fn, attempts=0, max_attempts=max_attempts)
        heapq.heappush(self._heap, item)
        self.stats["submitted"] += 1
        return True

    def _emit(self, event: dict[str, Any]) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 - 日志坏了不该拖垮队列
                pass

    # ------------------------------------------------------------ 执行
    async def run(self) -> list[TaskResult]:
        """把队列跑空，返回每个任务的结果（含重试后的最终结果）。"""
        loop = asyncio.get_running_loop()
        while self._heap or self._running:
            now = loop.time()
            while (self._heap and self._heap[0].ready_at <= now
                   and len(self._running) < self.workers):
                item = heapq.heappop(self._heap)
                task = asyncio.create_task(self._execute(item), name=item.key)
                self._running.add(task)
                task.add_done_callback(self._running.discard)
                now = loop.time()

            if self._running:
                timeout = None
                if self._heap:
                    timeout = max(0.0, self._heap[0].ready_at - loop.time())
                done, _ = await asyncio.wait(
                    self._running, timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED)
                # 结果已经在 _execute 里收集，这里只是取出异常防止警告
                for task in done:
                    if task.exception() is not None:
                        pass
            elif self._heap:
                await asyncio.sleep(max(0.0, self._heap[0].ready_at - loop.time()))

        results, self._results = self._results, []
        return results

    async def _execute(self, item: _Item) -> None:
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        attempt = item.attempts + 1
        try:
            if self.timeout:
                value = await asyncio.wait_for(item.fn(), timeout=self.timeout)
            else:
                value = await item.fn()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - 统一判定是否值得重试
            timed_out = isinstance(exc, asyncio.TimeoutError)
            if timed_out:
                self.stats["timed_out"] += 1
            limit = item.max_attempts if item.max_attempts is not None else self.retry.max_attempts
            retryable = (attempt < limit) and isinstance(exc, self.retry.retry_on)
            if retryable:
                delay = self.retry.delay_for(attempt)
                self.stats["retried"] += 1
                self._emit({"type": "retry", "key": item.key, "attempt": attempt,
                            "delay": round(delay, 2),
                            "error": f"{type(exc).__name__}: {exc}"})
                item.attempts = attempt
                item.ready_at = loop.time() + delay
                heapq.heappush(self._heap, item)
                return
            self.stats["failed"] += 1
            self._results.append(TaskResult(
                key=item.key, ok=False,
                error=f"{type(exc).__name__}: {exc}",
                attempts=attempt, elapsed=time.perf_counter() - started))
            self._emit({"type": "task_failed", "key": item.key,
                        "attempts": attempt, "error": f"{type(exc).__name__}: {exc}"})
            return

        self.stats["succeeded"] += 1
        self._results.append(TaskResult(
            key=item.key, ok=True, value=value, attempts=attempt,
            elapsed=time.perf_counter() - started))
        self._emit({"type": "task_done", "key": item.key, "attempts": attempt,
                    "elapsed": round(time.perf_counter() - started, 3)})

    # ------------------------------------------------------------ 便捷
    async def map(
        self,
        items: list[tuple[str, TaskFn]],
        *,
        priority: int = 0,
    ) -> list[TaskResult]:
        """批量入队并跑空。"""
        for key, fn in items:
            self.submit(key, fn, priority=priority)
        return await self.run()

    def summary(self) -> dict[str, Any]:
        return {"workers": self.workers, "timeout": self.timeout,
                "max_attempts": self.retry.max_attempts, **self.stats}


__all__ = ["RetryPolicy", "TaskQueue", "TaskResult"]
