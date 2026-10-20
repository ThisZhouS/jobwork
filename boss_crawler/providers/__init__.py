"""外部数据源（目前只有天眼查）。

同步与异步两条路径写同一套表，可按批量大小选用：

* :mod:`~boss_crawler.providers.tianyancha` —— 同步 HTTP 客户端与鉴权
* :mod:`~boss_crawler.providers.relations` —— 返回值的纯函数解析（可单测）
* :mod:`~boss_crawler.providers.dd` —— 同步背调编排：读库 → 查询 → 写库
* :mod:`~boss_crawler.providers.tyc_spider` —— 异步 spider（挂在通用引擎上）
* :mod:`~boss_crawler.providers.tyc_pipelines` —— 落库管道
* :mod:`~boss_crawler.providers.tyc_async` —— 异步编排入口
"""
from .dd import (
    DueDiligenceOptions,
    DueDiligenceResult,
    estimate_cost,
    investigate,
    name_score,
    pick_best,
    print_summary,
)
from .relations import (
    classify_invest,
    parse_dishonest,
    parse_profile,
    parse_relations,
    parse_risks,
    parse_zhixing,
    risk_summary,
    to_percent,
    verdict,
)
from .tianyancha import TianyanchaClient, TianyanchaError, load_token
from .tyc_async import AsyncRunResult, run_due_diligence_async, run_sync
from .tyc_pipelines import ProfilePipeline, RelationPipeline, RiskBufferPipeline, SkipLogPipeline
from .tyc_spider import TianyanchaSpider

__all__ = [
    "AsyncRunResult",
    "DueDiligenceOptions",
    "DueDiligenceResult",
    "ProfilePipeline",
    "RelationPipeline",
    "RiskBufferPipeline",
    "SkipLogPipeline",
    "TianyanchaClient",
    "TianyanchaError",
    "TianyanchaSpider",
    "classify_invest",
    "estimate_cost",
    "investigate",
    "load_token",
    "name_score",
    "parse_dishonest",
    "parse_profile",
    "parse_relations",
    "parse_risks",
    "parse_zhixing",
    "pick_best",
    "print_summary",
    "risk_summary",
    "run_due_diligence_async",
    "run_sync",
    "to_percent",
    "verdict",
]
