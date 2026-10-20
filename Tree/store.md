# boss_crawler/store —— 持久化层

本地 JSONL 是主存（可断点续跑），PostgreSQL 是可查询副本（元数据与向量同行）。

## 文件

| 文件 | 职责 | 关键符号 |
|---|---|---|
| `__init__.py` | 门面 | `JobStore` `Database` `expand_inputs` `load_raw_records` `load_clean_records` `merge_record` … |
| `jsonl.py` | JSONL 落地 | `JobStore`（`upsert` `flush` `export_csv` `records`） |
| `dataset.py` | 数据集加载（消除 CLI 里 4 处重复） | `expand_inputs` `merge_record` `load_raw_records` `load_clean_records` |
| `schema.py` | **表结构唯一事实来源** | `SCHEMA_SQL` `JOB_COLUMNS` `COMPANY_COLUMNS` |
| `postgres.py` | 连接 + 建表 + 写入 + 检索 + 统计 | `Database` `DatabaseError` `resolve_password` |

## 表

| 表 | 说明 |
|---|---|
| `jobs` | 岗位元数据 + JD 结构化列 + 向量列（同一行） |
| `companies` | 公司元数据 + 向量列 |
| `skills` / `job_skills` | 技能实体 / 岗位-技能关联（多对多） |
| `benefits` / `job_benefits` | 福利实体 / 岗位-福利关联 |
| `embedding_runs` | 每次向量化批次的可追溯记录 |

视图：`job_vector_status`、`company_vector_status`。

## 关键约定

* **改表结构只改 `schema.py`**：`db-init` 执行 `SCHEMA_SQL`（全部语句幂等），
  新增列用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 追加，保证老库可平滑升级；
* `JOB_COLUMNS` **故意不含向量列**，否则 `db-load` 重载会把已算好的向量清空；
* `embedding_hash` 是向量化原文的指纹，`embed` 只补缺失/变更的行（第二次运行 0 调用）；
* 本机无 pgvector 时用 `real[]` + `cosine_similarity()`（O(n)，万级以内够用）；
  检测到 `vector` 扩展会自动加 `vector(N)` 列与 HNSW 索引。

## 扩展方式

* 加字段：`schema.py` 加列 → `postgres.py` 的 `JOB_COLUMNS` 加列 → `structuring` 产出该字段；
* 加检索维度：`search_jobs` / `search_companies` 已在 `_search` 里统一处理相似度排序；
* 向量模型换了：`embedding.py` 的 `ARK_MODEL` + `config.EMBED_DIM`，`_sync_dimensions` 会重建向量列。
