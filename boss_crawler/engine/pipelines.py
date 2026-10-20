"""Item 管道：对 spider 产出的每条结果做串行加工（清洗、校验、落库）。

对标 Scrapy 的 ``Item Pipeline``。约定：

* 每个管道实现 ``process_item(item) -> Item | None``，返回 ``None`` 表示丢弃；
* 可以是普通函数也可以是 ``async def``，引擎两种都接受；
* 管道按注册顺序执行，前一个的输出就是后一个的输入；
* 单个管道抛异常只丢这条 item 并记一次 ``pipeline_error``，不影响其它请求。

新增一种产物（例如「关系边」）只需要写一个管道并注册，spider 与引擎都不用改。
"""
from __future__ import annotations

import inspect
from typing import Any, Iterable

from .item import Item


class ItemPipeline:
    """管道基类。默认原样放行。"""

    async def open(self) -> None:
        """引擎启动时调用一次（建连接、开文件放这里）。"""

    async def close(self) -> None:
        """引擎收尾时调用一次（提交事务、关连接放这里）。"""

    async def process_item(self, item: Item) -> Item | None:
        return item


class PipelineManager:
    """按顺序执行管道，负责异常隔离与 awaitable 适配。"""

    def __init__(self, pipelines: Iterable[Any] | None = None, *, stats: Any = None,
                 signals: Any = None, logger: Any = None) -> None:
        self.pipelines = list(pipelines or [])
        self.stats = stats
        self.signals = signals
        self.logger = logger

    async def open(self) -> None:
        for pipeline in self.pipelines:
            hook = getattr(pipeline, "open", None)
            if hook is not None:
                await _maybe_await(hook())

    async def close(self) -> None:
        for pipeline in reversed(self.pipelines):
            if hasattr(pipeline, "close"):
                await _maybe_await(pipeline.close())

    async def process(self, item: Item) -> Item | None:
        """依次过管道；任一环丢弃则整条丢弃。"""
        current: Item | None = item
        for pipeline in self.pipelines:
            if current is None:
                break
            try:
                current = await _maybe_await(pipeline.process_item(current))
            except Exception as exc:
                if self.logger is not None:
                    self.logger.error(f"管道 {type(pipeline).__name__} 处理 {item.item_type} 失败：{exc}")
                if self.stats is not None:
                    self.stats.inc("pipeline_error")
                if self.signals is not None:
                    await self.signals.send("pipeline_error", item=item, pipeline=pipeline, exception=exc)
                return None
        if current is None:
            if self.stats is not None:
                self.stats.inc("item_dropped")
            return None
        if self.stats is not None:
            self.stats.inc("item_scraped")
        if self.signals is not None:
            await self.signals.send("item_scraped", item=current)
        return current

    def __len__(self) -> int:
        return len(self.pipelines)


async def _maybe_await(value: Any) -> Any:
    """兼容同步/异步两种写法。"""
    if inspect.isawaitable(value):
        return await value
    return value
