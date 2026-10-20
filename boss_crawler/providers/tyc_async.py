"""异步背调入口：把 spider、管道、引擎组装成一个可调的协程。

与同步版 :func:`boss_crawler.providers.dd.investigate` 的关系：

* 同步版：一条直线跑完，代码简单、便于调试，适合几十家的小批量；
* 异步版（这里）：走引擎的队列 + 并发 + 重试，吞吐高、可观测，适合放大到几百上千家。

两者写同一套表，可混用。``dd`` 命令通过 ``--engine`` 选择。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..engine import Engine, Logger, Settings, SignalManager
from .tyc_pipelines import ProfilePipeline, RelationPipeline, RiskBufferPipeline, SkipLogPipeline
from .tyc_spider import TianyanchaSpider


@dataclass
class AsyncRunResult:
    """异步任务的结果摘要。"""

    stats: dict[str, Any] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)
    spent: float = 0.0
    elapsed: float = 0.0

    def summary_lines(self) -> list[str]:
        s = self.stats
        return [
            f"公司：计划 {s.get('request_scheduled', 0)} 个请求，"
            f"成功 {s.get('response_received', 0)}，失败 {s.get('response_failed', 0)}",
            f"重试 {s.get('request_retried', 0)} 次，去重 {s.get('request_dropped', 0)} 个",
            f"入库：档案 {s.get('item_scraped', 0)} 条 item，风险 {s.get('risk_rows_buffered', 0)} 行",
            f"花费：约 ¥{self.spent:.2f}",
        ]


async def run_due_diligence_async(
    db: Any,
    companies: list[dict],
    *,
    token: str | None = None,
    concurrency: int = 4,
    download_delay: float = 0.35,
    retry_times: int = 3,
    min_percent: float = 20.0,
    max_related: int = 3,
    skip_risks: bool = False,
    only_relations: bool = False,
    max_cost: float = 30.0,
    log_level: str = "info",
    signals: SignalManager | None = None,
) -> AsyncRunResult:
    """跑一次异步背调。所有写入在引擎收尾前提交。"""
    spider = TianyanchaSpider(
        companies,
        token=token,
        min_percent=min_percent,
        max_related=max_related,
        skip_risks=skip_risks,
        only_relations=only_relations,
        max_cost=max_cost,
    )
    settings = Settings(
        {
            "CONCURRENT_REQUESTS": concurrency,
            "DOWNLOAD_DELAY": download_delay,
            "RETRY_TIMES": retry_times,
            "LOG_LEVEL": log_level,
        }
    )
    logger = Logger(log_level)
    skip_pipeline = SkipLogPipeline(db, logger=logger)
    signals = signals or SignalManager()
    failures: list[dict] = []

    async def on_gave_up(**kwargs) -> None:
        """重试用尽仍失败的请求：记下来，别让公司静默消失。"""
        response = kwargs.get("response")
        request = kwargs.get("request")
        if response is None or request is None:
            return
        api = request.meta.get("api") or "?"
        reason = response.error_reason or (str(response.error) if response.error else f"status={response.status}")
        code = f"（error_code={response.error_code}）" if response.error_code else ""
        failures.append({
            "company_key": request.meta.get("company_key"),
            "api": api,
            "note": f"{api} 失败：{reason}{code}",
        })

    signals.connect("request_gave_up", on_gave_up)

    engine = Engine(
        spider,
        settings=settings,
        signals=signals,
        logger=logger,
        pipelines=[
            ProfilePipeline(db),
            RelationPipeline(db),
            RiskBufferPipeline(db),
            skip_pipeline,
        ],
    )

    stats = await engine.run()

    # 成本按接口分组记进统计，便于收尾打印
    for api, price in spider.cost_by_api.items():
        engine.stats.add_group("cost", api, price)

    # 引擎只负责写，不负责提交——事务边界留给调用方
    commit = getattr(db, "commit", None)
    if callable(commit):
        commit()

    elapsed = float(stats.get("elapsed_s", 0.0))
    return AsyncRunResult(
        stats=engine.stats.summary(),
        skipped=skip_pipeline.skipped + failures,
        spent=round(spider.spent, 2),
        elapsed=elapsed,
    )


def run_sync(db: Any, companies: list[dict], **kwargs: Any) -> AsyncRunResult:
    """给同步调用方用的包装：内部起事件循环。"""
    return asyncio.run(run_due_diligence_async(db, companies, **kwargs))
