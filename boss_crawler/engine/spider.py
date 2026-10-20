"""Spider 基类：定义「抓什么」和「怎么解析」。

对标 Scrapy 的 ``Spider``。一个 spider 只需两件事：

* :meth:`start_requests` —— 产出初始 ``Request``；
* :meth:`parse`（以及 ``Request.callback`` 指向的其它方法）—— 消费
  ``Response``，产出 ``Item`` 或新的 ``Request``。

引擎按 ``request.callback`` 找方法名分发，所以一条链可以有很多步
（搜索 → 详情 → 风险），每一步一个方法，互不干扰。

覆盖 :meth:`should_retry` 可以加入业务侧的重试判断（HTTP 200 但 body 报错）。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Union

from .item import Item, Request, Response

Output = Union[Request, Item]


class Spider:
    """所有 spider 的基类。"""

    name: str = "spider"
    # 覆盖引擎默认配置，写法与 Scrapy 的 custom_settings 一致
    custom_settings: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)
        self._closed = False

    # ---------------------------------------------------------------- 生命周期
    async def opened(self) -> None:
        """引擎启动后、发请求前调用一次。"""

    async def closed(self, reason: str = "finished") -> None:
        """引擎收尾时调用一次。"""

    # ---------------------------------------------------------------- 产出
    async def start_requests(self) -> AsyncIterator[Request]:
        """初始请求。子类必须实现（async generator）。"""
        raise NotImplementedError
        yield  # pragma: no cover  — 让类型检查知道这是 async generator

    async def parse(self, response: Response) -> AsyncIterator[Output]:
        """默认回调：子类覆盖。"""
        raise NotImplementedError
        yield  # pragma: no cover

    # ---------------------------------------------------------------- 策略
    def should_retry(self, response: Response, attempt: int) -> bool | None:
        """业务侧重试判断。返回 ``None`` 表示交给引擎的 ``RetryPolicy``。"""
        return None

    def callback_for(self, request: Request):
        """按名字取回调方法，找不到就用 ``parse``。"""
        method = getattr(self, request.callback, None)
        if method is None or not callable(method):
            return self.parse
        return method

    def __repr__(self) -> str:
        return f"<Spider {self.name}>"
