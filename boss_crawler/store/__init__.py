"""存储层：本地 JSONL 主存 + PostgreSQL（元数据与向量同行）。

* :mod:`boss_crawler.store.jsonl` —— 抓取结果的 JSONL/CSV 落地，按 job_id 去重；
* :mod:`boss_crawler.store.dataset` —— 输入展开与记录合并（多份 JSONL 合并成一份数据集）；
* :mod:`boss_crawler.store.schema` —— 建表 DDL 与列定义（唯一的表结构事实来源）；
* :mod:`boss_crawler.store.postgres` —— 连接、元数据写入、向量检索与统计。
"""
from .dataset import expand_inputs, load_clean_records, load_raw_records, merge_record
from .jsonl import JobStore
from .postgres import (
    COMPANY_COLUMNS,
    JOB_COLUMNS,
    SCHEMA_SQL,
    Database,
    DatabaseError,
    resolve_password,
)

__all__ = [
    "JobStore",
    "expand_inputs",
    "merge_record",
    "load_raw_records",
    "load_clean_records",
    "Database",
    "DatabaseError",
    "resolve_password",
    "SCHEMA_SQL",
    "JOB_COLUMNS",
    "COMPANY_COLUMNS",
]
