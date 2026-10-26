"""应用层存储：背调证据、原数据、打分、适配度、简历版本、报错日志。

与 :mod:`boss_crawler.store.postgres` 分工：

* ``postgres.py`` 管**采集层**（jobs / companies / tyc_*），逻辑已经很密，
  不去动它，避免把 173 条老测试搅乱；
* 本模块管**应用层**（``store/schema_app.sql`` 里那批表），给前端和流水线用。

设计上大量用 ``jsonb``：证据的形态会变（不同站点字段不同），
先按"结构化但不固定列"存，等口径稳定了再抽列。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

# 放在包内，wheel 安装后也能找到；仓库根 db/ 不再是运行期依赖。
SCHEMA_FILE = Path(__file__).with_name("schema_app.sql")


def _json(value: Any) -> str:
    """把任意对象转成 jsonb 参数。日期/Decimal 之类统一走 str。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _dumps_row(row: Any) -> Any:
    """把 RealDict 里的 date/Decimal 转成可 JSON 化的值。"""
    if isinstance(row, dict):
        return {k: _dumps_row(v) for k, v in row.items()}
    if isinstance(row, (list, tuple)):
        return [_dumps_row(v) for v in row]
    if hasattr(row, "isoformat"):
        return row.isoformat()
    if isinstance(row, float) and row != row:  # NaN
        return None
    return row


def dedupe_key(
    agent: str,
    *,
    company_key: str = "",
    url: str = "",
    title: str = "",
    published_at: str = "",
    snippet: str = "",
) -> str:
    """证据去重键。

    必须带 ``company_key``：同一篇报道可能同时提到多家公司，但它是各家
    各自的证据，不能因为 URL 相同就互相覆盖。

    内容指纹优先级：URL > 标题+日期 > 摘要正文。都为空时同一公司同一
    agent 只保留一条占位记录。
    """
    seed = url.strip() or f"{title.strip()}|{published_at.strip()}"
    if not seed.strip("|"):
        seed = snippet.strip()
    if not seed:
        seed = f"{agent}|unknown"
    return hashlib.md5(f"{company_key}|{agent}|{seed}".encode("utf-8")).hexdigest()


class AppStore:
    """应用层读写。复用 :class:`PostgresDB` 的连接，不另开池。"""

    def __init__(self, db) -> None:
        self.db = db

    # ------------------------------------------------------------------ 建表
    def init_schema(self, path: Path | None = None) -> dict:
        if path is None:
            # 基线脚本版本化为 app/001；后续增量迁移在 store/migrations/ 里登记。
            self.db.apply_migrations([("app/001", SCHEMA_FILE.read_text(encoding="utf-8"))])
        else:
            with self.db.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
            self.db.commit()
        return {"ok": True, "tables": self.table_names()}

    def table_names(self) -> list[str]:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT tablename FROM pg_tables
                   WHERE schemaname = 'public' ORDER BY tablename"""
            )
            return [row["tablename"] for row in cur.fetchall()]

    # ------------------------------------------------------------------ 运行记录
    def start_run(self, options: dict | None = None) -> int:
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT INTO app_run (status, options) VALUES ('running', %s) RETURNING id",
                (_json(options or {}),),
            )
            run_id = cur.fetchone()["id"]
        self.db.commit()
        return int(run_id)

    def finish_run(self, run_id: int, status: str, summary: dict | None = None) -> None:
        with self.db.cursor() as cur:
            cur.execute(
                """UPDATE app_run SET finished_at = now(), status = %s, summary = %s
                   WHERE id = %s""",
                (status, _json(summary or {}), run_id),
            )
        self.db.commit()

    def get_run(self, run_id: int) -> dict | None:
        with self.db.cursor() as cur:
            cur.execute("SELECT * FROM app_run WHERE id = %s", (run_id,))
            row = cur.fetchone()
        return _dumps_row(row) if row else None

    # ------------------------------------------------------------------ 背调证据
    def save_evidence(
        self,
        company_key: str,
        agent: str,
        findings: Iterable[Any],
        *,
        run_id: int | None = None,
    ) -> int:
        """写某公司某 agent 的证据：本次结果为准，先清掉该 agent 的旧证据。

        不这样做的话，上一次运行里已经判为无关、但本次被过滤掉的行会一直留在库里，
        继续参与打分——agent 的相关性判断就白做了。
        """
        rows = []
        for finding in findings:
            payload = getattr(finding, "meta", None) or {}
            url = str(getattr(finding, "url", "") or "")
            title = str(getattr(finding, "title", "") or "")
            published = getattr(finding, "published_at", None)
            if published:
                published_str = published.isoformat() if hasattr(published, "isoformat") else str(published)
            else:
                published_str = ""
            rows.append((
                company_key,
                run_id,
                agent,
                str(getattr(finding, "source", "") or agent),
                title,
                url,
                str(getattr(finding, "snippet", "") or ""),
                published_str or None,
                getattr(finding, "author", None),
                getattr(finding, "sentiment", None),
                getattr(finding, "weight", None),
                _json(payload),
                dedupe_key(
                    agent,
                    company_key=company_key,
                    url=url,
                    title=title,
                    published_at=str(published_str),
                    snippet=str(getattr(finding, "snippet", "") or ""),
                ),
            ))
        if not rows:
            return 0

        sql = """
            INSERT INTO backduty_evidence
                (company_key, run_id, agent, source, title, url, snippet,
                 published_at, author, sentiment, weight, payload, dedupe_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (company_key, dedupe_key) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                snippet = EXCLUDED.snippet,
                sentiment = EXCLUDED.sentiment,
                weight = EXCLUDED.weight,
                payload = EXCLUDED.payload,
                fetched_at = now()
        """
        with self.db.transaction():
            with self.db.cursor() as cur:
                cur.execute(
                    "DELETE FROM backduty_evidence WHERE company_key = %s AND agent = %s",
                    (company_key, agent),
                )
                cur.executemany(sql, rows)
        return len(rows)

    def clear_evidence(self, company_key: str, agent: str) -> int:
        """清掉某公司某 agent 的旧证据（本次明确查无结果时用）。"""
        with self.db.cursor() as cur:
            cur.execute(
                "DELETE FROM backduty_evidence WHERE company_key = %s AND agent = %s",
                (company_key, agent),
            )
            deleted = cur.rowcount
        self.db.commit()
        return int(deleted or 0)

    def save_agent_summary(self, company_key: str, agent: str, summary: dict, *,
                           run_id: int | None = None,
                           evidence_count: int | None = None) -> None:
        """保存 AI agent 对证据的结构化摘要（每公司每 agent 保留最新一份）。"""
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO backduty_summary
                       (company_key, agent, run_id, summary, evidence_count)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (company_key, agent) DO UPDATE SET
                       run_id = EXCLUDED.run_id,
                       summary = EXCLUDED.summary,
                       evidence_count = EXCLUDED.evidence_count,
                       created_at = now()""",
                (company_key, agent, run_id, _json(summary), evidence_count),
            )
        self.db.commit()

    def clear_agent_summary(self, company_key: str, agent: str) -> int:
        with self.db.cursor() as cur:
            cur.execute(
                "DELETE FROM backduty_summary WHERE company_key = %s AND agent = %s",
                (company_key, agent),
            )
            deleted = cur.rowcount
        self.db.commit()
        return int(deleted or 0)

    def agent_summaries(self, company_key: str) -> list[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT agent, run_id, summary, evidence_count, created_at
                   FROM backduty_summary WHERE company_key = %s ORDER BY agent""",
                (company_key,),
            )
            return [_dumps_row(row) for row in cur.fetchall()]

    def evidence_for(self, company_key: str, *, limit: int | None = None) -> list[dict]:
        sql = ("SELECT agent, source, title, url, snippet, published_at, author, "
               "sentiment, weight, payload FROM backduty_evidence "
               "WHERE company_key = %s ORDER BY fetched_at DESC")
        params: list[Any] = [company_key]
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, params)
            return [_dumps_row(row) for row in cur.fetchall()]

    @staticmethod
    def _summary_of(row: dict) -> dict:
        return {
            "total": int(row.get("total") or 0),
            "negative": int(row.get("negative") or 0),
            "positive": int(row.get("positive") or 0),
            "sources": [s for s in (row.get("sources") or []) if s],
        }

    def evidence_summary(self, company_key: str) -> dict:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT count(*) AS total,
                          count(*) FILTER (WHERE sentiment < 0) AS negative,
                          count(*) FILTER (WHERE sentiment > 0) AS positive,
                          array_agg(DISTINCT agent) AS sources
                   FROM backduty_evidence WHERE company_key = %s""",
                (company_key,),
            )
            row = cur.fetchone() or {}
        return self._summary_of(row)

    def evidence_summaries(self, company_keys: Sequence[str]) -> dict[str, dict]:
        """批量版 ``evidence_summary``，供列表页避免 N+1 查询。"""
        keys = list(dict.fromkeys(str(k) for k in company_keys if k))
        if not keys:
            return {}
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT company_key, count(*) AS total,
                          count(*) FILTER (WHERE sentiment < 0) AS negative,
                          count(*) FILTER (WHERE sentiment > 0) AS positive,
                          array_agg(DISTINCT agent) AS sources
                   FROM backduty_evidence
                   WHERE company_key = ANY(%s)
                   GROUP BY company_key""",
                (keys,),
            )
            rows = cur.fetchall()
        return {row["company_key"]: self._summary_of(row) for row in rows}

    # ------------------------------------------------------------------ 原数据
    def save_raw(self, company_key: str, agent: str, payload: Any, *,
                 run_id: int | None = None) -> None:
        """天眼查这类「不总结、直接存」的原始产出。"""
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO backduty_raw (company_key, agent, run_id, payload)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (company_key, agent) DO UPDATE SET
                       payload = EXCLUDED.payload, fetched_at = now(), run_id = EXCLUDED.run_id""",
                (company_key, agent, run_id, _json(payload)),
            )
        self.db.commit()

    def get_raw(self, company_key: str, agent: str) -> Any | None:
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT payload FROM backduty_raw WHERE company_key = %s AND agent = %s",
                (company_key, agent),
            )
            row = cur.fetchone()
        return row["payload"] if row else None

    # ------------------------------------------------------------------ 打分
    def save_company_score(self, company_key: str, card, *, run_id: int | None = None,
                           extra: dict | None = None) -> int:
        """存一份打分。``extra`` 里可放劳务派遣等独立字段。"""
        dims = [
            {"name": dim.name, "score": dim.score, "weight": dim.weight, "reason": dim.reason}
            for dim in getattr(card, "dimensions", []) or []
        ]
        extra = extra or {}
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO company_score
                       (company_key, run_id, total, grade, verdict, dimensions, advice, notes,
                        is_labor_dispatch, labor_dispatch_reason, labor_dispatch_evidence)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    company_key, run_id,
                    float(getattr(card, "total", 0.0) or 0.0),
                    getattr(card, "grade", None),
                    getattr(card, "verdict", None),
                    _json(dims),
                    _json(list(getattr(card, "advice", []) or [])),
                    _json(list(getattr(card, "notes", []) or [])),
                    extra.get("is_labor_dispatch"),
                    extra.get("labor_dispatch_reason"),
                    _json(extra.get("labor_dispatch_evidence") or []),
                ),
            )
            score_id = cur.fetchone()["id"]
        self.db.commit()
        return int(score_id)

    def latest_company_scores(self, *, limit: int = 200) -> list[dict]:
        """每家公司只取最新一份。"""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT * FROM (
                       SELECT DISTINCT ON (company_key)
                              company_key, total, grade, verdict, dimensions, advice, notes,
                              is_labor_dispatch, labor_dispatch_reason,
                              labor_dispatch_evidence, created_at
                       FROM company_score
                       ORDER BY company_key, created_at DESC
                   ) latest
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (limit,),
            )
            return [_dumps_row(row) for row in cur.fetchall()]

    def latest_company_score(self, company_key: str) -> dict | None:
        """单家公司的评分详情，供详情页精确查询（不受列表 limit 影响）。"""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT company_key, total, grade, verdict, dimensions, advice, notes,
                          is_labor_dispatch, labor_dispatch_reason,
                          labor_dispatch_evidence, created_at
                   FROM company_score WHERE company_key = %s
                   ORDER BY created_at DESC LIMIT 1""",
                (company_key,),
            )
            row = cur.fetchone()
        return _dumps_row(row) if row else None

    def latest_job_fit(self, job_id: str) -> dict | None:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT job_id, resume_id, total, grade, verdict, dimensions, advice, created_at
                   FROM job_fit WHERE job_id = %s
                   ORDER BY created_at DESC LIMIT 1""",
                (job_id,),
            )
            row = cur.fetchone()
        return _dumps_row(row) if row else None

    def company_score_series(self, company_key: str, *, limit: int = 60) -> list[dict]:
        """一家公司的打分历史——前端"点字段看折线图"用。"""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT * FROM (
                       SELECT created_at, total, grade, dimensions
                       FROM company_score WHERE company_key = %s
                       ORDER BY created_at DESC LIMIT %s
                   ) recent
                   ORDER BY created_at ASC""",
                (company_key, limit),
            )
            rows = [_dumps_row(row) for row in cur.fetchall()]
        series = []
        for row in rows:
            dims = {dim["name"]: dim["score"] for dim in (row.get("dimensions") or [])}
            series.append({"at": row["created_at"], "total": row["total"],
                           "grade": row.get("grade"), **dims})
        return series

    def save_job_fit(self, job_id: str, card, *, resume_id: int | None = None,
                     run_id: int | None = None) -> int:
        dims = [
            {"name": dim.name, "score": dim.score, "weight": dim.weight, "reason": dim.reason}
            for dim in getattr(card, "dimensions", []) or []
        ]
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO job_fit
                       (job_id, resume_id, run_id, total, grade, verdict, dimensions, advice)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    job_id, resume_id, run_id,
                    float(getattr(card, "total", 0.0) or 0.0),
                    getattr(card, "grade", None),
                    getattr(card, "verdict", None),
                    _json(dims),
                    _json(list(getattr(card, "advice", []) or [])),
                ),
            )
            fit_id = cur.fetchone()["id"]
        self.db.commit()
        return int(fit_id)

    def latest_job_fits(self, *, limit: int = 200) -> list[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT * FROM (
                       SELECT DISTINCT ON (job_id)
                              job_id, resume_id, total, grade, verdict, dimensions,
                              advice, created_at
                       FROM job_fit ORDER BY job_id, created_at DESC
                   ) latest
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (limit,),
            )
            return [_dumps_row(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------ 简历版本
    def save_resume(self, content: dict, *, name: str | None = None,
                    job_id: str | None = None, parent_id: int | None = None,
                    questions: list | None = None, answers: list | None = None,
                    confirmed: bool = False) -> int:
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO resume_version
                       (name, job_id, parent_id, content, questions, answers, confirmed)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (name or str(content.get("name") or content.get("姓名") or "简历"),
                 job_id, parent_id, _json(content),
                 _json(questions) if questions is not None else None,
                 _json(answers) if answers is not None else None,
                 bool(confirmed)),
            )
            resume_id = cur.fetchone()["id"]
        self.db.commit()
        return int(resume_id)

    def latest_resume(self, *, confirmed_only: bool = False) -> dict | None:
        sql = "SELECT * FROM resume_version"
        if confirmed_only:
            sql += " WHERE confirmed"
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self.db.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        return _dumps_row(row) if row else None

    def resume_version(self, resume_id: int) -> dict | None:
        with self.db.cursor() as cur:
            cur.execute("SELECT * FROM resume_version WHERE id = %s", (resume_id,))
            row = cur.fetchone()
        return _dumps_row(row) if row else None

    def resume_versions(self, *, limit: int = 12) -> list[dict]:
        """版本列表只取元数据；正文由 ``resume_version`` 按需读取。"""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT id, name, job_id, parent_id, confirmed, created_at,
                          content->>'target' AS target,
                          CASE WHEN jsonb_typeof(content->'skills') = 'array'
                               THEN jsonb_array_length(content->'skills') ELSE 0 END AS skill_count,
                          CASE WHEN jsonb_typeof(questions) = 'array'
                               THEN jsonb_array_length(questions) ELSE 0 END AS question_count,
                          CASE WHEN jsonb_typeof(answers) = 'array'
                               THEN jsonb_array_length(answers) ELSE 0 END AS answer_count
                   FROM resume_version
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (limit,),
            )
            return [_dumps_row(row) for row in cur.fetchall()]

    def confirm_resume(self, resume_id: int) -> bool:
        with self.db.cursor() as cur:
            cur.execute(
                "UPDATE resume_version SET confirmed = TRUE WHERE id = %s",
                (resume_id,),
            )
            updated = cur.rowcount
        self.db.commit()
        return bool(updated)

    # ------------------------------------------------------------------ 日志
    def log_event(self, *, agent: str, message: str, level: str = "error",
                  tool: str | None = None, status: str | None = None,
                  code: str | None = None, context: Any = None,
                  run_id: int | None = None) -> int:
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_error
                       (run_id, agent, tool, level, status, code, message, context)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (run_id, agent, tool, level, status, code, message,
                 _json(context) if context is not None else None),
            )
            error_id = cur.fetchone()["id"]
        self.db.commit()
        return int(error_id)

    def recent_errors(self, *, limit: int = 50, run_id: int | None = None) -> list[dict]:
        sql = "SELECT * FROM agent_error"
        params: list[Any] = []
        if run_id is not None:
            sql += " WHERE run_id = %s"
            params.append(run_id)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, params)
            return [_dumps_row(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------ 登录态
    def set_login(self, platform: str, state_dir: str, ok: bool, detail: str | None = None) -> None:
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO platform_login (platform, state_dir, ok, detail)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (platform) DO UPDATE SET
                       state_dir = EXCLUDED.state_dir, ok = EXCLUDED.ok,
                       detail = EXCLUDED.detail, updated_at = now()""",
                (platform, state_dir, bool(ok), detail),
            )
        self.db.commit()

    def logins(self) -> dict[str, bool]:
        with self.db.cursor() as cur:
            cur.execute("SELECT platform, ok FROM platform_login")
            return {row["platform"]: bool(row["ok"]) for row in cur.fetchall()}

    # ------------------------------------------------------------------ 前端数据
    def jobs_for_fit(self, *, limit: int = 50, job_ids: Sequence[str] | None = None) -> list[dict]:
        """取待算适配度的岗位详情（带 JD 正文的更优先）。"""
        sql = """SELECT job_id, title, company_key, company_name, salary, salary_min, salary_max,
                        experience, degree, city, district, industry, skills, welfare, description, url
                 FROM jobs"""
        params: list[Any] = []
        if job_ids:
            sql += " WHERE job_id = ANY(%s)"
            params.append(list(job_ids))
        sql += " ORDER BY (description IS NOT NULL) DESC, job_id LIMIT %s"
        params.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, params)
            return [_dumps_row(row) for row in cur.fetchall()]

    def jobs_summary(self, company_key: str) -> dict:
        """给评分用的岗位汇总：数量、薪资区间、福利标签、技能标签。

        薪资字段是"元/月"，库里存的是 ``salary_min/max``（整数），
        单位换算在采集层已经归一，这里直接用。
        """
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT count(*) AS count,
                          max(salary_max) AS salary_max,
                          min(salary_min) AS salary_min,
                          count(*) FILTER (WHERE salary_max IS NOT NULL) AS with_salary
                   FROM jobs WHERE company_key = %s""",
                (company_key,),
            )
            row = cur.fetchone() or {}
            cur.execute(
                """SELECT welfare FROM jobs
                   WHERE company_key = %s AND welfare IS NOT NULL""",
                (company_key,),
            )
            welfare: list[str] = []
            for item in cur.fetchall():
                for tag in (item.get("welfare") or []):
                    if tag and tag not in welfare:
                        welfare.append(str(tag))
        return {
            "count": int(row.get("count") or 0),
            "salary_max": row.get("salary_max"),
            "salary_min": row.get("salary_min"),
            "with_salary": int(row.get("with_salary") or 0),
            "welfare": welfare,
        }

    def company_targets(self, *, limit: int | None = 50, include_anonymous: bool = False) -> list[dict]:
        try:
            return self.db.company_targets(include_anonymous=include_anonymous, limit=limit)
        except Exception:  # noqa: BLE001 - 老库没有该字段时退化
            with self.db.cursor() as cur:
                cur.execute(
                    """SELECT company_key, company_name, count(*) AS job_count
                       FROM jobs WHERE company_key IS NOT NULL
                       GROUP BY company_key, company_name
                       ORDER BY job_count DESC LIMIT %s""",
                    (limit,),
                )
                return [_dumps_row(row) for row in cur.fetchall()]

    def data_view(self, *, limit: int = 100) -> dict:
        """前端「数据」页签要的一整块。"""
        scores = {row["company_key"]: row for row in self.latest_company_scores(limit=limit)}
        fits = {row["job_id"]: row for row in self.latest_job_fits(limit=limit)}
        active_resume = self.latest_resume(confirmed_only=True)
        active_resume_id = active_resume["id"] if active_resume else None

        with self.db.cursor() as cur:
            cur.execute(
                """SELECT company_key, company_name, count(*) AS job_count
                   FROM jobs WHERE company_key IS NOT NULL AND company_name IS NOT NULL
                   GROUP BY company_key, company_name ORDER BY job_count DESC LIMIT %s""",
                (limit,),
            )
            companies = [_dumps_row(row) for row in cur.fetchall()]

        summaries = self.evidence_summaries([row["company_key"] for row in companies])
        company_rows = []
        for row in companies:
            key = row["company_key"]
            score = scores.get(key)
            company_rows.append({
                "company_key": key,
                "name": row["company_name"],
                "job_count": int(row["job_count"] or 0),
                "score": None if not score else {
                    "total": score["total"], "grade": score["grade"],
                    "dimensions": {dim["name"]: dim["score"]
                                   for dim in (score["dimensions"] or [])},
                    "verdict": score["verdict"], "advice": score["advice"],
                    # 劳务派遣：None 表示信息不足，别当 false
                    "is_labor_dispatch": score.get("is_labor_dispatch"),
                    "labor_dispatch_reason": score.get("labor_dispatch_reason"),
                },
                "evidence": summaries.get(key, self._summary_of({})),
            })

        jobs = self.jobs_for_fit(limit=limit)
        job_rows = []
        for job in jobs:
            fit = fits.get(job["job_id"])
            job_rows.append({
                "id": job["job_id"],
                "title": job["title"],
                "company": job.get("company_name"),
                "company_key": job.get("company_key"),
                "salary": job.get("salary"),
                "city": job.get("city"),
                "fit": None if not fit else {
                    "total": fit["total"], "grade": fit["grade"],
                    "dimensions": {d["name"]: d["score"] for d in (fit["dimensions"] or [])},
                    "advice": fit["advice"], "verdict": fit["verdict"],
                    "resume_id": fit.get("resume_id"),
                    "resume_state": "unknown" if not fit.get("resume_id")
                    else ("current" if fit["resume_id"] == active_resume_id else "stale"),
                    "at": fit.get("created_at"),
                },
            })
        return {"companies": company_rows, "jobs": job_rows}

    def stats(self) -> dict:
        out: dict[str, Any] = {}
        with self.db.cursor() as cur:
            for table in ("jobs", "companies", "backduty_evidence", "backduty_raw",
                          "company_score", "job_fit", "resume_version", "agent_error"):
                try:
                    cur.execute(f"SELECT count(*) AS n FROM {table}")   # noqa: S608 - 表名来自常量
                    out[table] = int(cur.fetchone()["n"])
                except Exception:  # noqa: BLE001 - 表可能还没建
                    # 连接已进入失败事务，必须回滚，否则后续表全部查不了
                    self.db.rollback()
                    out[table] = None
        return out
