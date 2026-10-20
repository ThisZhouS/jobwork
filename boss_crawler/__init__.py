"""BOSS直聘 岗位采集 / 结构化 / 向量化（scrapling + PostgreSQL）。

包结构与依赖方向（只允许上层依赖下层，禁止反向）：

    cli/          命令行入口，只做参数解析与编排
      ↓
    crawl/        采集：浏览器会话、接口解析、抓取编排
    structuring/  结构化：JD 拆解、清洗、聚合（纯函数、无 IO）
    store/        持久化：JSONL 主存 + PostgreSQL（元数据与向量同行）
    embedding.py  向量化客户端
    export.py     Excel 导出
      ↓
    filters.py config.py types.py industry_codes.py   叶子模块

跨包调用请使用各子包的门面（``boss_crawler.crawl``、``boss_crawler.structuring``、
``boss_crawler.store``），不要深入内部模块，便于后续替换实现。
"""
from . import config  # noqa: F401
from .crawl import BossBrowser, JobCrawler, LoginRequired  # noqa: F401
from .store import Database, JobStore  # noqa: F401

__all__ = [
    "BossBrowser",
    "Database",
    "JobCrawler",
    "JobStore",
    "LoginRequired",
    "config",
]
__version__ = "0.3.0"
