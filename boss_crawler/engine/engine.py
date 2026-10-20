"""引擎主体：把调度器、下载器、spider、管道串起来跑。

对标 Scrapy 的 ``ExecutionEngine``。数据流：

```
spider.start_requests ──┐
                        ├─> Scheduler(队列/去重) ─> Worker × N ─> Downloader ─> Response
spider.parse ───────────┘                                                        │
       │                                                                         │
       ├─ 产出 Request ──> 回到 Scheduler（形成链路）                              │
       └─ 产出 Item ────> PipelineManager ──> 数据库/文件                          │
                                                                                 │
                        重试判定 <───────────────────────────────────────────────┘
```

收尾条件：**生产者结束 + 队列空 + 无在飞请求 + 无待重试**。四个条件都满足才关，
所以「链路中某一步刚产出新请求」不会被误判成结束。
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, AsyncIterator, Iterable

from .downloader import Downloader
from .item import Item, Request, Response
from .middleware import build_middlewares
from .pipelines import PipelineManager
from .retry import RetryPolicy
from .scheduler import Scheduler
from .settings import Settings
from .signals import SignalManager
from .spider import Spider
from .stats import Logger, Stats


class Engine:
    """一次采集任务的执行器。用完即弃，不做跨任务的全局状态。"""

    def __init__(
        self,
        spider: Spider,
        *,
        settings: Settings | None = None,
        downloader: Downloader | None = None,
        pipelines: Iterable[Any] | None = None,
        middlewares: list | None = None,
        signals: SignalManager | None = None,
        logger: Logger | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        self.spider = spider
        self.settings = (settings or Settings()).copy()
        for key, value in (getattr(spider, "custom_settings", {}) or {}).items():
            self.settings.set(key, value)

        self.stats = Stats()
        self.signals = signals or SignalManager()
        self.logger = logger or Logger(self.settings.get("LOG_LEVEL", "info"))
        self.retry_policy = RetryPolicy.from_settings(self.settings)
        self.scheduler = scheduler or Scheduler(int(self.settings.get("QUEUE_MAXSIZE", 0)))

        if downloader is None:
            chain = build_middlewares(self.settings, self.logger, middlewares)
            self.downloader = Downloader(self.settings, middlewares=chain, stats=self.stats)
        else:
            self.downloader = downloader

        self.pipelines = PipelineManager(
            pipelines, stats=self.stats, signals=self.signals, logger=self.logger
        )

        # ---- 收尾判定用到的状态
        self._inflight = 0
        self._delayed = 0
        self._producer_done = False
        self._finished = False
        self._stopping = False
        self._finish_lock = asyncio.Lock()
        self._delayed_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ 主入口
    async def run(self) -> dict[str, Any]:
        """跑完整个任务，返回统计摘要。"""
        await self.signals.send("engine_started", engine=self)
        await self.signals.send("spider_opened", spider=self.spider)
        await self.spider.opened()
        await self.pipelines.open()

        workers = max(1, int(self.settings.get("CONCURRENT_REQUESTS", 6))) + 1
        worker_tasks = [asyncio.create_task(self._worker(i), name=f"worker-{i}") for i in range(workers)]
        producer = asyncio.create_task(self._produce(), name="producer")

        total_timeout = float(self.settings.get("TOTAL_TIMEOUT", 0.0))
        reason = "finished"
        tasks = [producer, *worker_tasks]
        try:
            if total_timeout > 0:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=total_timeout)
            else:
                await asyncio.gather(*tasks)
        except asyncio.TimeoutError:
            reason = "timeout"
            self.logger.warn(f"总时限 {total_timeout}s 已到，提前收尾")
            self.scheduler.close()
            raise
        except asyncio.CancelledError:
            reason = "cancelled"
            self.scheduler.close()
            raise
        except Exception:
            # 生产者或回调抛异常时，worker 可能还阻塞在队列上，必须显式收掉，
            # 否则会留下 pending task（事件循环关闭时报 Event loop is closed）
            reason = "error"
            self.scheduler.close()
            raise
        finally:
            # 统一兜底：任何路径下都不留下未完成的 task
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for task in list(self._delayed_tasks):
                task.cancel()
            if self._delayed_tasks:
                await asyncio.gather(*self._delayed_tasks, return_exceptions=True)
            await self.pipelines.close()
            await self.downloader.close()
            await self.spider.closed(reason)
            await self.signals.send("spider_closed", spider=self.spider, reason=reason)
            await self.signals.send("engine_stopped", engine=self, reason=reason)

        self.stats.set("scheduler_enqueued", self.scheduler.enqueued)
        self.stats.set("scheduler_dropped", self.scheduler.dropped)
        return self.stats.summary()

    # 别名：语义更清楚的入口名
    crawl = run

    # ------------------------------------------------------------------ 生产
    async def _produce(self) -> None:
        try:
            async for request in self.spider.start_requests():
                if self._stopping:
                    break
                if await self.scheduler.enqueue(request):
                    self.stats.inc("request_scheduled")
                    await self.signals.send("request_scheduled", request=request, spider=self.spider)
                else:
                    self.stats.inc("request_dropped")
                    await self.signals.send("request_dropped", request=request, spider=self.spider)
        finally:
            self._producer_done = True
            await self._maybe_finish()

    # ------------------------------------------------------------------ 消费
    async def _worker(self, index: int) -> None:
        while True:
            # 已决定停（例如达到 MAX_ITEMS）就不再领新活，让队列自然排空
            if self._stopping:
                return
            request = await self.scheduler.next_request()
            if request is None:
                return
            if self._stopping:
                return
            self._inflight += 1
            try:
                await self._handle(request)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 单个请求出问题不该拖垮 worker
                self.logger.error(f"处理 {request} 时异常：{exc}")
                self.stats.inc("handle_error")
            finally:
                self._inflight -= 1
            await self._maybe_finish()

    async def _handle(self, request: Request) -> None:
        response = await self.downloader.fetch(request)
        if response.ok:
            self.stats.inc("response_received")
            await self.signals.send("response_received", response=response, spider=self.spider)
        else:
            self.stats.inc("response_failed")
            await self.signals.send("response_failed", response=response, spider=self.spider)

        # 业务侧优先判断，返回 None 则退回统一策略；无论哪种都受重试次数上限约束
        verdict = self.spider.should_retry(response, request.retry_times)
        if verdict is None:
            retry = self.retry_policy.should_retry(response, attempt=request.retry_times)
        else:
            retry = bool(verdict) and request.retry_times < self.retry_policy.times
        if retry:
            await self._schedule_retry(request, response)
            return

        if not response.ok:
            # 重试用尽仍失败：发一个明确的「放弃」信号，
            # 否则调用方只会看到「请求变少了」，说不清是哪家、为什么
            await self.signals.send("request_gave_up", request=request, response=response,
                                    spider=self.spider)
            if self.settings.get("DROP_FAILED", True):
                return

        async for output in _iter_outputs(self.spider.callback_for(request)(response)):
            if isinstance(output, Request):
                if self._stopping:
                    continue
                if await self.scheduler.enqueue(output):
                    self.stats.inc("request_scheduled")
                    await self.signals.send("request_scheduled", request=output, spider=self.spider)
                else:
                    self.stats.inc("request_dropped")
            elif isinstance(output, Item):
                await self.pipelines.process(output)
                await self._check_item_limit()

    async def _schedule_retry(self, request: Request, response: Response) -> None:
        attempt = request.retry_times + 1
        delay = self.retry_policy.delay_for(attempt)
        self.stats.inc("request_retried")
        await self.signals.send("request_retried", request=request, response=response,
                                attempt=attempt, delay=delay, spider=self.spider)
        self.logger.debug(f"重试 #{attempt} {request}，{delay}s 后重投")

        async def later() -> None:
            await asyncio.sleep(delay)
            if self._stopping or self._finished:
                self._delayed -= 1
                return
            await self.scheduler.enqueue(request.with_retry())
            self._delayed -= 1
            await self._maybe_finish()

        self._delayed += 1
        task = asyncio.create_task(later(), name=f"retry-{request.retry_times}")
        self._delayed_tasks.add(task)
        task.add_done_callback(self._delayed_tasks.discard)

    async def _check_item_limit(self) -> None:
        limit = int(self.settings.get("MAX_ITEMS", 0) or 0)
        if limit and self.stats.get("item_scraped") >= limit:
            self._stopping = True
            self.scheduler.close()

    # ------------------------------------------------------------------ 收尾
    async def _maybe_finish(self) -> None:
        """四个条件都满足才关调度器。用锁保护，避免多个 worker 同时判定。"""
        async with self._finish_lock:
            if self._finished:
                return
            if self._stopping:
                # 主动停止：只要在飞请求清空就收尾，不必等队列排空
                if self._inflight:
                    return
                self._finished = True
                self.scheduler.close()
                return
            if not self.settings.get("CLOSE_ON_EMPTY", True):
                return
            if not self._producer_done or self._inflight or self._delayed:
                return
            if not self.scheduler.empty():
                return
            self._finished = True
            self.scheduler.close()


async def _iter_outputs(value: Any) -> AsyncIterator[Any]:
    """统一 spider 回调的四种返回形态：async generator / coroutine / 列表 / 单个对象。"""
    if value is None:
        return
    if inspect.isasyncgen(value):
        async for item in value:
            yield item
        return
    if inspect.isawaitable(value):
        resolved = await value
        async for item in _iter_outputs(resolved):
            yield item
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield item
        return
    yield value
