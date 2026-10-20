"""轻量信号：在关键节点挂回调，用来做日志、统计、监控，而不侵入主流程。

对标 Scrapy 的 ``signals``。与 Scrapy 的区别是支持异步回调——引擎全程在
事件循环里，同步回调反而要多绕一层。

已定义的事件见 :data:`EVENTS`。新增事件只需在发布处 ``await signals.send(...)``，
监听方用 ``connect`` 挂上即可，双方互不依赖。
"""
from __future__ import annotations

import inspect
from collections import defaultdict
from typing import Any, Awaitable, Callable

EVENTS = {
    "engine_started",
    "engine_stopped",
    "spider_opened",
    "spider_closed",
    "request_scheduled",
    "request_dropped",      # 被去重或中间件丢弃
    "request_retried",
    "request_gave_up",      # 重试用尽仍失败：需要人工关注
    "response_received",
    "response_failed",
    "item_scraped",
    "item_dropped",         # 被管道丢弃
    "pipeline_error",
}

Handler = Callable[..., Any] | Callable[..., Awaitable[Any]]


class SignalManager:
    """事件收发。回调抛异常不会打断引擎，只记一条错误。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def connect(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    def disconnect(self, event: str, handler: Handler) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    def connected(self, event: str) -> int:
        return len(self._handlers.get(event, []))

    async def send(self, event: str, **payload: Any) -> list[Exception]:
        """触发事件，返回回调里吞掉的异常（便于测试断言）。"""
        errors: list[Exception] = []
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(**payload)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # 观测代码不该拖垮采集
                errors.append(exc)
        return errors
