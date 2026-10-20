"""引擎配置：默认值集中在一处，调用方只覆盖关心的项。

对标 Scrapy 的 ``settings``：大写键名、有默认值、可按 spider 覆盖。
"""
from __future__ import annotations

from typing import Any, Mapping

# 默认配置。改这里就是改全局默认；单个任务用 ``Settings(overrides=...)`` 覆盖。
DEFAULTS: dict[str, Any] = {
    # ---- 并发与节奏
    "CONCURRENT_REQUESTS": 6,          # 同时在飞的请求数上限
    "DOWNLOAD_DELAY": 0.2,             # 同一主机两次请求的最小间隔（秒）
    "AUTOTHROTTLE": True,              # 按实测延迟自动微调间隔
    "AUTOTHROTTLE_TARGET": 1.2,        # 目标延迟倍数：>1 更保守
    "AUTOTHROTTLE_MAX_DELAY": 8.0,
    # ---- 重试
    "RETRY_TIMES": 3,                  # 最多重试几次（不含首次）
    "RETRY_BACKOFF_BASE": 0.6,         # 指数退避基数：0.6, 1.2, 2.4 ...
    "RETRY_BACKOFF_MAX": 30.0,
    "RETRY_HTTP_CODES": (408, 425, 429, 500, 502, 503, 504),
    "RETRY_BUSINESS_CODES": (300005, 500, 501, 502),  # 业务侧可重试的错误码（spider 可覆盖）
    # ---- 队列
    "QUEUE_MAXSIZE": 0,                # 0 = 不限；>0 时生产者会被反压
    "CLOSE_ON_EMPTY": True,            # 队列空且无在飞请求即收尾
    "MAX_ITEMS": 0,                    # >0 时达到条数上限就停
    # ---- 超时
    "DOWNLOAD_TIMEOUT": 20.0,
    "TOTAL_TIMEOUT": 0.0,              # >0 时整个任务的总时限，超时收尾
    # ---- 观测
    "LOG_LEVEL": "info",               # debug | info | warn | error
    "STATS_INTERVAL": 0.0,             # >0 时按秒打印进度
}


class Settings:
    """只读为主、可覆盖的配置对象，支持属性与映射两种读法。"""

    def __init__(self, overrides: Mapping[str, Any] | None = None) -> None:
        self._values = dict(DEFAULTS)
        for key, value in (overrides or {}).items():
            self._values[key.upper()] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key.upper(), default)

    def set(self, key: str, value: Any) -> None:
        self._values[key.upper()] = value

    def update(self, mapping: Mapping[str, Any]) -> None:
        for key, value in mapping.items():
            self.set(key, value)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)

    def copy(self, overrides: Mapping[str, Any] | None = None) -> "Settings":
        merged = dict(self._values)
        merged.update({k.upper(): v for k, v in (overrides or {}).items()})
        return Settings(merged)

    # 属性式读取：settings.CONCURRENT_REQUESTS 也能用
    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __repr__(self) -> str:
        return f"<Settings {len(self._values)} keys>"
