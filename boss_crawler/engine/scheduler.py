"""调度器：优先队列 + 去重指纹 + 优雅关闭。

对标 Scrapy 的 ``Scheduler``（含 ``dupefilter``）。三个要点：

1. **优先级队列**：值越大越先出队。用自增序号做次级键，避免拿 ``Request``
   本身比较（它不可排序）。
2. **去重**：默认按 ``Request.fingerprint`` 去重；``dont_filter=True`` 的请求
   （例如重投）不去重，否则重试会被自己挡掉。
3. **关闭**：投一个哨兵到队尾，worker 取到后把它放回去再退出，这样所有 worker
   都能依次收到退出信号，不会被漏掉。
"""
from __future__ import annotations

import asyncio
import itertools
from collections.abc import Iterable

from .item import Request

# 哨兵用最低优先级入队，保证真实请求先被消费
_SENTINEL = object()
_LOWEST_PRIORITY = 1 << 62


class DupeFilter:
    """指纹集合。生产环境量小够用；要持久化可换成 Bloom/Redis 实现。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, fingerprint: str) -> bool:
        """已存在返回 True；否则记录并返回 False。"""
        if fingerprint in self._seen:
            return True
        self._seen.add(fingerprint)
        return False

    def __len__(self) -> int:
        return len(self._seen)


class Scheduler:
    """异步优先队列。

    参数
    ----
    maxsize:
        >0 时队列满会反压生产者（``enqueue`` 等待），用于限制内存占用。
    """

    def __init__(self, maxsize: int = 0, dupefilter: DupeFilter | None = None) -> None:
        self._queue: asyncio.Queue = asyncio.PriorityQueue(maxsize)
        self._seq = itertools.count()
        self.dupefilter = dupefilter or DupeFilter()
        self._closed = False
        self._enqueued = 0
        self._dropped = 0
        self._put_lock = asyncio.Lock()

    # ---------------------------------------------------------------- 入队
    async def enqueue(self, request: Request) -> bool:
        """入队。被去重或已关闭时返回 False。"""
        if self._closed:
            return False
        if not request.dont_filter and self.dupefilter.seen(request.fingerprint):
            self._dropped += 1
            return False
        await self._queue.put((-request.priority, next(self._seq), request))
        self._enqueued += 1
        return True

    async def enqueue_many(self, requests: Iterable[Request]) -> int:
        accepted = 0
        for request in requests:
            if await self.enqueue(request):
                accepted += 1
        return accepted

    # ---------------------------------------------------------------- 出队
    async def next_request(self) -> Request | None:
        """取下一个请求；调度器已关闭且已排空时返回 ``None``。"""
        while True:
            _, _, payload = await self._queue.get()
            if payload is _SENTINEL:
                await self._push_sentinel()   # 让其它 worker 也能收到退出信号
                return None
            return payload  # type: ignore[return-value]

    async def _push_sentinel(self) -> None:
        """把哨兵放回队尾。队列满时退化成异步等待，避免丢信号。"""
        item = (_LOWEST_PRIORITY, next(self._seq), _SENTINEL)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            asyncio.create_task(self._queue.put(item))

    # ---------------------------------------------------------------- 状态
    def close(self) -> None:
        """标记关闭并唤醒所有等待中的 worker。重复调用无副作用。"""
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait((_LOWEST_PRIORITY, next(self._seq), _SENTINEL))
        except asyncio.QueueFull:
            asyncio.create_task(self._queue.put((_LOWEST_PRIORITY, next(self._seq), _SENTINEL)))

    @property
    def closed(self) -> bool:
        return self._closed

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def enqueued(self) -> int:
        return self._enqueued

    @property
    def dropped(self) -> int:
        return self._dropped

    def __len__(self) -> int:
        return self._queue.qsize()
