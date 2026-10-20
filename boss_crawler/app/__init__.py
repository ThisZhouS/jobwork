"""应用层：把「采集 → 背调 → 打分 → 适配度 → 定向简历」编排成一条流水线。

前端（Electron 或任何 UI）只需要：

1. 调 :func:`boss_crawler.app.login.login_all` 让用户登录；
2. 调 :func:`boss_crawler.app.pipeline.run_pipeline` 跑一次；
3. 读 :meth:`boss_crawler.store.app_store.AppStore.data_view` 拿要展示的数据。

前端不需要知道 agent 叫什么、工具怎么调。
"""
from __future__ import annotations

from .login import PLATFORMS, login, login_all, login_platforms
from .pipeline import DEFAULT_PLATFORMS, PLATFORM_AGENTS, Options, Pipeline, run_pipeline
from .sources import JobSource, get_source, register_source, run_source, sources

__all__ = [
    "DEFAULT_PLATFORMS",
    "PLATFORMS",
    "PLATFORM_AGENTS",
    "JobSource",
    "Options",
    "Pipeline",
    "get_source",
    "login",
    "login_all",
    "login_platforms",
    "register_source",
    "run_pipeline",
    "run_source",
    "sources",
]
