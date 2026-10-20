"""采集统计：计数、耗时、分接口成本。收尾时一次性打印。

对标 Scrapy 的 ``stats``，额外支持「按 key 分组累加」（例如按接口统计花费）。
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


class Stats:
    """简单的计数器 + 分组累加器。"""

    # 这些键即使为 0 也会出现在 summary 里，调用方不必写 .get(...) 兜底
    STANDARD_KEYS = (
        "request_scheduled",
        "request_dropped",
        "request_retried",
        "response_received",
        "response_failed",
        "item_scraped",
        "item_dropped",
        "pipeline_error",
        "handle_error",
    )

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self._counters: dict[str, int | float] = defaultdict(int)
        self._groups: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    # ---------------------------------------------------------------- 计数
    def inc(self, key: str, value: int | float = 1) -> None:
        self._counters[key] += value

    def set(self, key: str, value: Any) -> None:
        self._counters[key] = value

    def get(self, key: str, default: Any = 0) -> Any:
        return self._counters.get(key, default)

    def add_group(self, group: str, key: str, value: float = 1.0) -> None:
        """按组累加，例如 ``add_group('cost', 'ic', 1.0)``。"""
        self._groups[group][key] += value

    def group(self, group: str) -> dict[str, float]:
        return dict(self._groups.get(group, {}))

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def rate(self) -> float:
        """每秒完成多少条（用 response_received 计数）。"""
        done = self.get("response_received")
        return round(done / self.elapsed, 2) if self.elapsed > 0 and done else 0.0

    # ---------------------------------------------------------------- 输出
    def summary(self) -> dict[str, Any]:
        data: dict[str, Any] = {key: 0 for key in self.STANDARD_KEYS}
        data.update(self._counters)
        data["elapsed_s"] = round(self.elapsed, 2)
        data["rate_per_s"] = self.rate
        for name, values in self._groups.items():
            data[f"by_{name}"] = dict(values)
        return data

    def format(self) -> str:
        """给命令行看的多行摘要。"""
        lines = [
            f"请求：发出 {self.get('request_scheduled')}，成功 {self.get('response_received')}，"
            f"失败 {self.get('response_failed')}，重试 {self.get('request_retried')}，"
            f"去重 {self.get('request_dropped')}",
            f"结果：入库 {self.get('item_scraped')}，丢弃 {self.get('item_dropped')}",
        ]
        cost = self.group("cost")
        if cost:
            total = sum(cost.values())
            detail = "，".join(f"{k} ¥{v:.2f}" for k, v in sorted(cost.items()) if v)
            lines.append(f"成本：约 ¥{total:.2f}（{detail}）")
        lines.append(f"耗时：{self.elapsed:.1f}s，吞吐 {self.rate} 次/秒")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<Stats {dict(self._counters)}>"


class Logger:
    """按级别过滤的极简日志器，避免引入 logging 配置的复杂度。"""

    LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}

    def __init__(self, level: str = "info", sink=None) -> None:
        self.threshold = self.LEVELS.get(str(level).lower(), 20)
        self._sink = sink or print
        self.records: list[tuple[str, str]] = []

    def _log(self, level: str, message: str) -> None:
        self.records.append((level, message))
        if self.LEVELS[level] >= self.threshold:
            self._sink(f"[{level}] {message}")

    def debug(self, message: str) -> None:
        self._log("debug", message)

    def info(self, message: str) -> None:
        self._log("info", message)

    def warn(self, message: str) -> None:
        self._log("warn", message)

    def error(self, message: str) -> None:
        self._log("error", message)
