"""通用异步采集内核（受 Scrapy 架构启发，但只保留用得上的部分）。

分层的对应关系：

| Scrapy | 这里 |
|---|---|
| Engine | :class:`~boss_crawler.engine.engine.Engine` |
| Scheduler + dupefilter | :mod:`~boss_crawler.engine.scheduler` |
| Downloader / AutoThrottle | :mod:`~boss_crawler.engine.downloader` |
| Downloader Middleware | :mod:`~boss_crawler.engine.middleware` |
| Spider | :class:`~boss_crawler.engine.spider.Spider` |
| Item Pipeline | :mod:`~boss_crawler.engine.pipelines` |
| Signals | :mod:`~boss_crawler.engine.signals` |
| Stats / Log | :mod:`~boss_crawler.engine.stats` |
| Settings | :mod:`~boss_crawler.engine.settings` |
| RetryMiddleware | :mod:`~boss_crawler.engine.retry` |

设计约束：**引擎不认识任何业务**。它只知道 ``Request`` / ``Response`` /
``Item`` 三个契约，所以加一种数据源只需写一个 spider + 若干管道，
加一种产物只需写一个管道，都不需要改引擎。
"""
from .downloader import Downloader, HostThrottle, HttpxTransport
from .engine import Engine
from .item import Item, Request, Response
from .middleware import (
    DownloaderMiddleware,
    HeaderMiddleware,
    JsonMiddleware,
    LoggingMiddleware,
    build_middlewares,
)
from .pipelines import ItemPipeline, PipelineManager
from .retry import RetryPolicy
from .scheduler import DupeFilter, Scheduler
from .settings import DEFAULTS, Settings
from .signals import EVENTS, SignalManager
from .spider import Spider
from .stats import Logger, Stats

__all__ = [
    "DEFAULTS",
    "EVENTS",
    "Downloader",
    "DownloaderMiddleware",
    "DupeFilter",
    "Engine",
    "HeaderMiddleware",
    "HostThrottle",
    "HttpxTransport",
    "Item",
    "ItemPipeline",
    "JsonMiddleware",
    "Logger",
    "LoggingMiddleware",
    "PipelineManager",
    "Request",
    "Response",
    "RetryPolicy",
    "Scheduler",
    "Settings",
    "SignalManager",
    "Spider",
    "Stats",
    "build_middlewares",
]
