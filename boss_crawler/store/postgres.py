"""PostgreSQL 访问层：连接、元数据写入、向量检索与统计。

对外主要用 :class:`Database`：一个上下文管理器，内部按职责分成三段
（建表 → 写入 → 检索），彼此不共享状态，方便单独测试。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterable, Sequence

import psycopg2
import psycopg2.extras

from .. import config
from ..structuring import skill_category
from .schema import COMPANY_COLUMNS, JOB_COLUMNS, SCHEMA_SQL

class DatabaseError(RuntimeError):
    """数据库不可用或凭据缺失。"""


def resolve_password() -> str:

    password = os.environ.get("PGPASSWORD") or ""
    if not password and config.PG_PASSWORD_FILE.exists():
        password = config.PG_PASSWORD_FILE.read_text(encoding="utf-8").strip()
    if not password:
        raise DatabaseError(
            f"未找到数据库密码：请设置环境变量 PGPASSWORD 或写入 {config.PG_PASSWORD_FILE}"
        )
    return password


class _CursorContext:
    """游标包装：块内异常时回滚。

    psycopg2 在事务中遇到 SQL 错误后，连接会停在
    ``InFailedSqlTransaction``，后续语句全部报错——即使调用方已经
    ``try/except`` 吞掉了原始异常。所以回滚必须发生在游标块退出时，
    而不是指望每个调用点自己记得。
    """

    def __init__(self, db: "Database", cur) -> None:
        self._db = db
        self._cur = cur

    def __enter__(self):
        return self._cur

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._cur.close()
        finally:
            if exc_type is not None:
                self._db.rollback()


class Database:
    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        log=print,
    ) -> None:
        self.host = host or config.PG_HOST
        self.port = port or config.PG_PORT
        self.user = user or config.PG_USER
        self.database = database or config.PG_DATABASE
        self.password = password or resolve_password()
        self.log = log
        self.conn = None
        self._pgvector = False
        self._vector_dim: int | None = None

    # ------------------------------------------------------------------ 连接
    def connect(self):
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(
                    host=self.host, port=self.port, user=self.user,
                    password=self.password, dbname=self.database,
                )
            except psycopg2.Error as exc:
                raise DatabaseError(f"连接 PostgreSQL 失败：{str(exc).strip()}") from exc
            self.conn.autocommit = False
        return self.conn

    def cursor(self) -> _CursorContext:
        return _CursorContext(
            self,
            self.connect().cursor(cursor_factory=psycopg2.extras.RealDictCursor),
        )

    def close(self) -> None:
        if self.conn is not None and not self.conn.closed:
            self.conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def commit(self) -> None:
        self.connect().commit()

    def rollback(self) -> None:
        if self.conn is not None and not self.conn.closed:
            try:
                self.conn.rollback()
            except psycopg2.Error:
                pass

    @contextmanager
    def transaction(self):
        """多语句原子操作：成功提交，任何异常回滚后原样抛出。"""
        try:
            yield self
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()

    # ------------------------------------------------------------------ 建表
    def has_pgvector(self) -> bool:
        with self.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            self._pgvector = cur.fetchone() is not None
        return self._pgvector

    def init_schema(self) -> dict:
        """建表 + 建函数 + （若可用）启用 pgvector 列与索引。"""
        self.connect()
        self.apply_migrations([("core/001", SCHEMA_SQL)])
        info = {"pgvector": self.has_pgvector(), "vector_column": False, "index": None}
        if info["pgvector"]:
            info.update(self._ensure_pgvector_columns())
        return info

    # ---------------------------------------------------------------- 迁移
    def apply_migrations(self, migrations: Sequence[tuple[str, str]]) -> list[str]:
        """按 version 升序执行尚未记录的迁移，每项一个事务。

        version 是持久化键：已有库首次升级时会把幂等的基线脚本重跑一遍，
        之后只有新增 version 才会执行。
        """
        self.connect()
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     text PRIMARY KEY,
                    applied_at  timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        self.commit()
        with self.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            done = {row["version"] for row in cur.fetchall()}
        applied: list[str] = []
        for version, sql in sorted(migrations):
            if version in done:
                continue
            with self.transaction():
                with self.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
            applied.append(version)
        return applied

    def _ensure_pgvector_columns(self) -> dict:
        """检测到 vector 扩展时：加 vector 列 + HNSW 索引（本机未实测）。"""
        result: dict[str, Any] = {"vector_column": False, "index": None}
        with self.cursor() as cur:
            cur.execute("SELECT embedding_dim FROM jobs WHERE embedding_dim IS NOT NULL LIMIT 1")
            row = cur.fetchone()
            dim = row["embedding_dim"] if row else 2048
            for table in ("jobs", "companies"):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS embedding_vec vector({dim})")
        self.commit()
        result["vector_column"] = True

        # 索引单独一个事务：HNSW 建失败时不能连带回滚刚加的向量列。
        try:
            with self.cursor() as cur:
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS jobs_embedding_vec_idx "
                    "ON jobs USING hnsw (embedding_vec vector_cosine_ops)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS companies_embedding_vec_idx "
                    "ON companies USING hnsw (embedding_vec vector_cosine_ops)"
                )
            self.commit()
            result["index"] = "hnsw"
        except psycopg2.Error as exc:
            self.rollback()
            self.log(f"  ! HNSW 索引创建失败（已忽略）：{str(exc).strip()}")
        return result

    # ------------------------------------------------------------------ 写入
    @staticmethod
    def _upsert_sql(table: str, columns: Sequence[str], key: str) -> str:
        cols = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != key)
        return (
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({key}) DO UPDATE SET {updates}, updated_at = now()"
        )

    def upsert_companies(self, companies: Iterable[dict], raw_by_key: dict | None = None) -> int:
        raw_by_key = raw_by_key or {}
        rows = []
        for company in companies:
            key = company.get("key") or company.get("company_name")
            rows.append((
                key, company.get("company_name"), company.get("legal_name"),
                bool(company.get("is_anonymous")), bool(company.get("is_truncated")),
                company.get("industry"), company.get("industry_code"),
                company.get("scale"), company.get("stage"), company.get("intro"),
                company.get("job_count") or 0, company.get("cities") or [],
                company.get("addresses") or [], company.get("address_source"),
                company.get("salary_min"), company.get("salary_max"),
                company.get("sample_titles") or [],
                json.dumps(raw_by_key.get(key), ensure_ascii=False) if raw_by_key.get(key) else None,
            ))
        if not rows:
            return 0
        with self.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur, self._upsert_sql("companies", COMPANY_COLUMNS, "company_key"), rows
            )
        self.commit()
        return len(rows)

    def upsert_jobs(self, jobs: Iterable[dict], raw_by_id: dict | None = None) -> int:
        raw_by_id = raw_by_id or {}
        rows = []
        missing_companies: dict[str, str] = {}
        skill_links: list[tuple[Any, str, str, str]] = []
        benefit_links: list[tuple[Any, str]] = []
        for job in jobs:
            company = job.get("company") or {}
            workplace = job.get("workplace") or {}
            company_key = company.get("key") or company.get("name")
            if company_key:
                missing_companies.setdefault(company_key, company.get("name") or company_key)
            job_id = job.get("job_id")
            jd_skills = [str(s) for s in (job.get("skills_all") or job.get("skills") or [])]
            for skill in dict.fromkeys(jd_skills):
                skill_links.append((job_id, skill, skill_category(skill), "jd+api"))
            for benefit in dict.fromkeys([str(b) for b in (job.get("jd_benefits") or [])]):
                benefit_links.append((job_id, benefit))
            rows.append((
                job.get("job_id"), job.get("title"), company_key,
                company.get("name"), company.get("legal_name"),
                job.get("salary"), job.get("salary_min"), job.get("salary_max"),
                job.get("salary_unit"), job.get("experience"), job.get("degree"),
                workplace.get("city"), workplace.get("district"),
                workplace.get("business_district"), workplace.get("detail"),
                workplace.get("full"), workplace.get("source"),
                company.get("industry"), company.get("industry_code"),
                [str(s) for s in (job.get("skills") or [])],
                [str(w) for w in (job.get("welfare") or [])],
                job.get("description"), job.get("url"), job.get("source_file"),
                # ---- JD 结构化 ----
                [str(x) for x in (job.get("responsibilities") or [])],
                [str(x) for x in (job.get("requirements") or [])],
                json.dumps(job.get("jd_sections") or {}, ensure_ascii=False),
                jd_skills,
                [str(x) for x in (job.get("jd_benefits") or [])],
                job.get("min_years"), job.get("max_years"),
                job.get("degree_required"), job.get("hiring_count"),
                job.get("work_schedule"), job.get("seniority"),
                bool(job.get("has_jd")), job.get("jd_length"),
                json.dumps(raw_by_id.get(job.get("job_id")), ensure_ascii=False)
                if raw_by_id.get(job.get("job_id")) else None,
            ))
        if not rows:
            return 0
        # 先把缺的公司补成占位行，保证外键不挡插入
        with self.cursor() as cur:
            cur.execute("SELECT company_key FROM companies")
            existing = {row["company_key"] for row in cur.fetchall()}
            stubs = [
                (key, name, key) for key, name in missing_companies.items() if key not in existing
            ]
            if stubs:
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO companies (company_key, company_name) VALUES (%s, %s) "
                    "ON CONFLICT (company_key) DO NOTHING",
                    stubs,
                )
            psycopg2.extras.execute_batch(
                cur, self._upsert_sql("jobs", JOB_COLUMNS, "job_id"), rows
            )
            self._sync_dimensions(cur, skill_links, benefit_links)
        self.commit()
        return len(rows)

    @staticmethod
    def _sync_dimensions(cur, skill_links, benefit_links) -> None:
        """重建 job_skills / job_benefits 关联（幂等：先删本批 job 的关联再插）。"""
        if skill_links:
            job_ids = list({link[0] for link in skill_links})
            unique_skills = sorted({link[1] for link in skill_links if link[1]})
            categories: dict[str, str] = {}
            for _job_id, skill, category, _source in skill_links:
                categories.setdefault(skill, category)
            if unique_skills:
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO skills (name, category) VALUES (%s, %s) "
                    "ON CONFLICT (name) DO UPDATE SET category = COALESCE(skills.category, EXCLUDED.category)",
                    [(skill, categories.get(skill, "其他")) for skill in unique_skills],
                )
            cur.execute("DELETE FROM job_skills WHERE job_id = ANY(%s)", (job_ids,))
            skill_payload = [(job_id, skill, source) for job_id, skill, _c, source in skill_links if skill]
            if skill_payload:
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO job_skills (job_id, skill, source) VALUES (%s, %s, %s) "
                    "ON CONFLICT (job_id, skill) DO NOTHING",
                    skill_payload,
                )
        if benefit_links:
            job_ids = list({link[0] for link in benefit_links})
            unique = sorted({link[1] for link in benefit_links if link[1]})
            if unique:
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO benefits (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                    [(name,) for name in unique],
                )
            cur.execute("DELETE FROM job_benefits WHERE job_id = ANY(%s)", (job_ids,))
            benefit_payload = [(job_id, benefit) for job_id, benefit in benefit_links if benefit]
            if benefit_payload:
                psycopg2.extras.execute_batch(
                    cur,
                    "INSERT INTO job_benefits (job_id, benefit) VALUES (%s, %s) "
                    "ON CONFLICT (job_id, benefit) DO NOTHING",
                    benefit_payload,
                )

    # ------------------------------------------------------------------ 向量
    def embedding_targets(self, owner_type: str, model: str, hashes: dict[str, str]) -> list[str]:
        """返回需要（重新）向量化的 id：没向量、换模型、或原文指纹变了。"""
        table, key = ("jobs", "job_id") if owner_type == "job" else ("companies", "company_key")
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {key} AS id, embedding_model, embedding_hash, embedding FROM {table}"
            )
            current = {row["id"]: row for row in cur.fetchall()}
        pending = []
        for owner_id, digest in hashes.items():
            row = current.get(owner_id)
            if row is None:
                continue  # 库里没有这条记录，跳过
            if (
                row["embedding"] is None
                or row["embedding_model"] != model
                or row["embedding_hash"] != digest
            ):
                pending.append(owner_id)
        return pending

    def save_embeddings(
        self,
        owner_type: str,
        model: str,
        items: Sequence[dict],
        *,
        mirror_pgvector: bool = True,
    ) -> int:
        """items: [{id, content, hash, vector}]，向量与元数据写在同一行。"""
        table, key = ("jobs", "job_id") if owner_type == "job" else ("companies", "company_key")
        if not items:
            return 0
        use_vector = mirror_pgvector and self._pgvector
        with self.cursor() as cur:
            for item in items:
                vector = [float(x) for x in item["vector"]]
                if use_vector:
                    cur.execute(
                        f"UPDATE {table} SET embedding = %s, embedding_vec = %s::vector, "
                        "embedding_model = %s, embedding_dim = %s, embedding_hash = %s, "
                        "embed_text = %s, embedded_at = now() WHERE " + key + " = %s",
                        (vector, vector, model, len(vector), item["hash"],
                         item["content"], item["id"]),
                    )
                else:
                    cur.execute(
                        f"UPDATE {table} SET embedding = %s, embedding_model = %s, "
                        "embedding_dim = %s, embedding_hash = %s, embed_text = %s, "
                        "embedded_at = now() WHERE " + key + " = %s",
                        (vector, model, len(vector), item["hash"], item["content"], item["id"]),
                    )
        self.commit()
        return len(items)

    def log_run(
        self, owner_type: str, model: str, dim: int | None, count: int, note: str = ""
    ) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO embedding_runs (owner_type, model, dim, item_count, finished_at, note) "
                "VALUES (%s, %s, %s, %s, now(), %s)",
                (owner_type, model, dim, count, note),
            )
        self.commit()

    # ------------------------------------------------------------------ 检索
    def search_jobs(self, vector: Sequence[float], k: int = 5) -> list[dict]:
        return self._search("jobs", "job_id", vector, k)

    def search_companies(self, vector: Sequence[float], k: int = 5) -> list[dict]:
        return self._search("companies", "company_key", vector, k)

    def _search(self, table: str, key: str, vector: Sequence[float], k: int) -> list[dict]:
        values = [float(x) for x in vector]
        if self._pgvector:
            sql = (
                f"SELECT {key} AS id, *, 1 - (embedding_vec <=> %s::vector) AS score "
                f"FROM {table} WHERE embedding_vec IS NOT NULL "
                "ORDER BY embedding_vec <=> %s::vector LIMIT %s"
            )
            params: tuple[Any, ...] = (values, values, k)
        else:
            sql = (
                f"SELECT {key} AS id, *, cosine_similarity(embedding, %s) AS score "
                f"FROM {table} WHERE embedding IS NOT NULL "
                "ORDER BY score DESC NULLS LAST LIMIT %s"
            )
            params = (values, k)
        with self.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict:
        with self.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS jobs, count(embedding) AS jobs_embedded, "
                "count(DISTINCT company_key) AS companies FROM jobs"
            )
            jobs = dict(cur.fetchone())
            cur.execute(
                "SELECT count(*) AS companies, count(embedding) AS companies_embedded FROM companies"
            )
            companies = dict(cur.fetchone())
            cur.execute("SELECT embedding_model, embedding_dim, count(*) AS n FROM jobs "
                        "WHERE embedding IS NOT NULL GROUP BY 1, 2 ORDER BY n DESC LIMIT 1")
            model = cur.fetchone()
            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())) AS size")
            size = cur.fetchone()
            cur.execute("SELECT count(*) AS runs FROM embedding_runs")
            runs = cur.fetchone()
            cur.execute(
                "SELECT count(*) FILTER (WHERE has_jd) AS with_jd, "
                "count(*) FILTER (WHERE cardinality(responsibilities) > 0) AS with_duties, "
                "count(*) FILTER (WHERE cardinality(requirements) > 0) AS with_reqs, "
                "count(*) FILTER (WHERE min_years IS NOT NULL) AS with_years, "
                "count(*) FILTER (WHERE hiring_count IS NOT NULL) AS with_hiring "
                "FROM jobs"
            )
            structured = dict(cur.fetchone())
            cur.execute("SELECT count(*) AS n FROM skills")
            skill_total = cur.fetchone()
            cur.execute("SELECT count(*) AS n FROM job_skills")
            skill_links = cur.fetchone()
            cur.execute("SELECT count(*) AS n FROM job_benefits")
            benefit_links = cur.fetchone()
        return {
            **jobs, **companies,
            "model": dict(model) if model else None,
            "database_size": size["size"] if size else None,
            "embedding_runs": runs["runs"] if runs else 0,
            "pgvector": self._pgvector,
            "structured": structured,
            "skills": skill_total["n"] if skill_total else 0,
            "job_skills": skill_links["n"] if skill_links else 0,
            "job_benefits": benefit_links["n"] if benefit_links else 0,
        }

    # ------------------------------------------------------------ 天眼查背调
    def company_targets(self, *, include_anonymous: bool = False, limit: int | None = None) -> list[dict]:
        """取出待背调的公司（默认跳过脱敏公司，它们无法在天眼查定位）。"""
        sql = "SELECT company_key, company_name, legal_name, is_anonymous FROM companies"
        if not include_anonymous:
            sql += " WHERE NOT is_anonymous"
        sql += " ORDER BY company_key"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self.cursor() as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]

    def save_tyc_profile(self, company_key: str, profile: dict, *, match_score: float | None,
                         match_note: str | None, raw: dict) -> None:
        """写入/更新一家公司的工商档案。"""
        columns = [
            "company_key", "tyc_id", "credit_code", "name", "legal_person", "reg_status",
            "reg_capital", "estiblish_time", "reg_location", "industry", "business_scope",
            "phone", "email", "website", "staff_num", "company_org_type",
            "match_score", "match_note", "raw",
        ]
        values = [
            company_key, profile.get("tyc_id"), profile.get("credit_code"), profile.get("name"),
            profile.get("legal_person"), profile.get("reg_status"), profile.get("reg_capital"),
            profile.get("estiblish_time"), profile.get("reg_location"), profile.get("industry"),
            profile.get("business_scope"), profile.get("phone"), profile.get("email"),
            profile.get("website"), profile.get("staff_num"), profile.get("company_org_type"),
            match_score, match_note, json.dumps(raw, ensure_ascii=False, default=str),
        ]
        placeholders = ", ".join(["%s"] * len(columns))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns[1:])
        sql = (
            f"INSERT INTO tyc_company ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (company_key) DO UPDATE SET {updates}, fetched_at = now()"
        )
        with self.cursor() as cur:
            cur.execute(sql, values)

    def replace_tyc_relations(self, company_key: str, rows: list[dict]) -> int:
        """整批替换一家公司的关系边（重跑不产生重复）。"""
        with self.cursor() as cur:
            cur.execute("DELETE FROM tyc_relation WHERE from_key = %s", (company_key,))
            if not rows:
                return 0
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO tyc_relation "
                "(from_key, relation, to_tyc_id, to_name, to_credit_code, to_reg_status, percent, grade, depth, via_key) "
                "VALUES %s ON CONFLICT (from_key, relation, to_name, via_key) DO NOTHING",
                [
                    (
                        company_key, r["relation"], r.get("to_tyc_id"), r.get("to_name"),
                        r.get("to_credit_code"), r.get("to_reg_status"), r.get("percent"),
                        r.get("grade"), r.get("depth", 1), r.get("via_key"),
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def replace_tyc_risks(self, related_key: str, rows: list[dict]) -> int:
        """整批替换某个主体名下的风险事件。"""
        with self.cursor() as cur:
            cur.execute("DELETE FROM tyc_risk WHERE related_key = %s", (related_key,))
            if not rows:
                return 0
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO tyc_risk "
                "(entity_key, entity_name, related_key, relation, risk_type, occurred_at, "
                " department, reason, removed_at, detail) VALUES %s",
                [
                    (
                        r["entity_key"], r.get("entity_name"), related_key, r.get("relation", "self"),
                        r["risk_type"], r.get("occurred_at"), r.get("department"),
                        r.get("reason"), r.get("removed_at"),
                        json.dumps(r.get("detail"), ensure_ascii=False, default=str),
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def log_tyc_call(self, company_key: str | None, call: dict, *, ok: bool = True,
                     note: str | None = None) -> None:
        """记录一次接口调用（含价格），用于核对成本。"""
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO tyc_fetch_log "
                "(company_key, api, keyword, error_code, http_status, elapsed_ms, price, ok, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    company_key, call.get("api"), call.get("keyword"), call.get("code"),
                    call.get("http"), call.get("ms"), call.get("price"), ok, note,
                ),
            )

    def tyc_stats(self) -> dict:
        """背调进度与成本统计。"""
        with self.cursor() as cur:
            cur.execute("SELECT count(*) AS companies FROM companies")
            total = cur.fetchone()["companies"]
            cur.execute("SELECT count(*) AS n FROM tyc_company")
            fetched = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM tyc_relation")
            relations = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM tyc_risk")
            risks = cur.fetchone()["n"]
            cur.execute("SELECT coalesce(sum(price), 0) AS cost, count(*) AS calls FROM tyc_fetch_log")
            spend = dict(cur.fetchone())
            cur.execute(
                "SELECT risk_type, count(*) AS n FROM tyc_risk GROUP BY 1 ORDER BY n DESC"
            )
            by_type = {row["risk_type"]: row["n"] for row in cur.fetchall()}
            cur.execute(
                "SELECT grade, count(*) AS n FROM tyc_relation WHERE relation = 'subsidiary' GROUP BY 1 ORDER BY n DESC"
            )
            by_grade = {row["grade"]: row["n"] for row in cur.fetchall()}
        return {
            "companies": total,
            "fetched": fetched,
            "relations": relations,
            "risks": risks,
            "calls": spend["calls"],
            "cost": round(float(spend["cost"]), 2),
            "risks_by_type": by_type,
            "subsidiaries_by_grade": by_grade,
        }


