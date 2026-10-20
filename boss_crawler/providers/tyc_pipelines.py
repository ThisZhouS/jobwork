"""落库管道：把 spider 产出的 ``Item`` 写进 PostgreSQL。

为什么用单线程执行器：**psycopg2 的连接不是线程安全的**。引擎在事件循环里跑，
数据库是同步驱动，所以必须把阻塞调用挪出事件循环；用 ``max_workers=1`` 的
线程池既能去除阻塞，又保证同一连接始终只被一个线程使用。

风险行按公司缓冲、收尾时一次性替换：`replace_tyc_risks` 是「先删后插」，
如果每条风险都调用一次，后一条会把前一条删掉。
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..engine import Item, ItemPipeline


class _DbPipeline(ItemPipeline):
    """所有落库管道的公共部分：串行执行 + 统计。"""

    def __init__(self, db: Any, *, stats: Any = None, logger: Any = None) -> None:
        self.db = db
        self.stats = stats
        self.logger = logger
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db")

    async def _run(self, func, *args, **kwargs) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    async def close(self) -> None:
        await self.flush()
        self._executor.shutdown(wait=True)

    async def flush(self) -> None:
        """子类覆盖：收尾时把缓冲区写下去。"""


class ProfilePipeline(_DbPipeline):
    """工商档案。"""

    async def process_item(self, item: Item) -> Item | None:
        if item.item_type != "company_profile":
            return item
        await self._run(
            self.db.save_tyc_profile,
            item["company_key"],
            item["profile"],
            match_score=item.get("match_score"),
            match_note=item.get("match_note"),
            raw=item.get("raw") or {},
        )
        return item


class RelationPipeline(_DbPipeline):
    """关系边（母公司 / 控股子公司 / 分支）。"""

    async def process_item(self, item: Item) -> Item | None:
        if item.item_type != "company_relations":
            return item
        await self._run(self.db.replace_tyc_relations, item["company_key"], item["rows"])
        return item


class RiskBufferPipeline(_DbPipeline):
    """风险事件：按公司缓冲，收尾时逐公司替换。"""

    def __init__(self, db: Any, **kwargs: Any) -> None:
        super().__init__(db, **kwargs)
        self._buffers: dict[str, list[dict]] = {}
        self._touched: set[str] = set()

    async def process_item(self, item: Item) -> Item | None:
        if item.item_type == "company_risk_watch":
            key = item["related_key"]
            self._touched.add(key)
            self._buffers.setdefault(key, [])
            return item
        if item.item_type != "company_risk":
            return item
        key = item["related_key"]
        self._touched.add(key)
        bucket = self._buffers.setdefault(key, [])
        bucket.extend(item["rows"])
        if self.stats is not None:
            self.stats.inc("risk_rows_buffered", len(item["rows"]))
        return item

    async def flush(self) -> None:
        for key in sorted(self._touched):
            rows = self._buffers.get(key, [])
            await self._run(self.db.replace_tyc_risks, key, rows)
            if self.stats is not None:
                self.stats.inc("companies_with_risks_flushed")


class SkipLogPipeline(_DbPipeline):
    """记录没匹配上的公司，便于人工复核。"""

    def __init__(self, db: Any, **kwargs: Any) -> None:
        super().__init__(db, **kwargs)
        self.skipped: list[dict] = []

    async def process_item(self, item: Item) -> Item | None:
        if item.item_type != "company_skipped":
            return item
        self.skipped.append({"company_key": item["company_key"], "note": item["note"]})
        if self.logger is not None:
            self.logger.warn(f"跳过 {item['company_name']}：{item['note']}")
        return item

    async def flush(self) -> None:
        if self.skipped and self.stats is not None:
            self.stats.inc("companies_skipped", len(self.skipped))
