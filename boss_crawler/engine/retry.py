"""重试策略：决定「要不要重试」和「等多久再试」。

对标 Scrapy 的 ``RetryMiddleware`` + ``Retry`` 设置。与 Scrapy 的差别是
同时支持**业务错误码**：天眼查这类接口常常 HTTP 200 但在 body 里返回
``error_code``，纯看状态码会把「限流」当成成功。

退避用指数加随机抖动，避免一批请求在同一时刻齐刷刷重试。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import AbstractSet

from .item import Response


@dataclass
class RetryPolicy:
    """重试判定与退避计算。

    * ``times``：最多重试几次（不含首次）；
    * ``http_codes``：这些状态码视为可重试失败；
    * ``business_codes``：body 里的 ``error_code`` 命中这些值时重试；
    * ``retry_on_error``：网络异常（超时、连接失败）是否重试。
    """

    times: int = 3
    backoff_base: float = 0.6
    backoff_max: float = 30.0
    http_codes: AbstractSet[int] = field(
        default_factory=lambda: frozenset({408, 425, 429, 500, 502, 503, 504})
    )
    business_codes: AbstractSet[int] = field(default_factory=frozenset)
    retry_on_error: bool = True
    jitter: bool = True

    def should_retry(self, response: Response, *, attempt: int) -> bool:
        """``attempt`` 是已重试次数；达到上限就不再重试。"""
        if attempt >= self.times:
            return False
        if response.error is not None:
            return self.retry_on_error
        if response.status in self.http_codes:
            return True
        if response.error_code is not None and response.error_code in self.business_codes:
            return True
        return False

    def delay_for(self, attempt: int) -> float:
        """第 ``attempt`` 次重试前等待的秒数（指数退避 + 抖动）。"""
        delay = min(self.backoff_base * (2 ** max(attempt - 1, 0)), self.backoff_max)
        if self.jitter:
            delay *= random.uniform(0.7, 1.3)
        return round(max(delay, 0.0), 3)

    @classmethod
    def from_settings(cls, settings) -> "RetryPolicy":
        return cls(
            times=int(settings.get("RETRY_TIMES", 3)),
            backoff_base=float(settings.get("RETRY_BACKOFF_BASE", 0.6)),
            backoff_max=float(settings.get("RETRY_BACKOFF_MAX", 30.0)),
            http_codes=frozenset(settings.get("RETRY_HTTP_CODES") or ()),
            business_codes=frozenset(settings.get("RETRY_BUSINESS_CODES") or ()),
        )
