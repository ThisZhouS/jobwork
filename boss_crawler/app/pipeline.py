"""编排：把你的组合方案落成一条可配置的流水线。

```
[招聘爬虫] --岗位--> jobs 表
     |
     v  读 company_key
[天眼查/知乎/微博/贴吧 agent] --证据--> backduty_evidence / backduty_raw
     |
     v  读证据 + 原始数据
[公司打分 agent] --风险/待遇/压力/环境/福利--> company_score
     |
     v  读岗位 + 简历
[岗位 agent] --适配度--> job_fit
     |
     v  用户确认后
[简历 agent] --定向简历--> resume_version
```

每一段都可以单独关掉（方案要求"天眼查/知乎/微博/贴吧/适配度/简历均设置为可选"）。
每一步的产出都落库，所以前端只读库、不需要关心流程怎么跑的。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..agents import AgentContext, AgentRequest, Finding, get
from ..store.app_store import AppStore
from . import sources

Emit = Callable[[dict], Any]

#: 平台开关 -> 背调 agent
PLATFORM_AGENTS: dict[str, str] = {
    "tianyancha": "tianyancha_web",
    "tianyan_ai": "tianyan_ai",
    "zhihu": "zhihu",
    "weibo": "weibo",
    "tieba": "tieba",
}

DEFAULT_PLATFORMS = ("tianyancha", "zhihu", "weibo", "tieba")


@dataclass
class Options:
    """一次运行的开关与筛选条件。"""

    platforms: tuple[str, ...] = DEFAULT_PLATFORMS
    source: str = "boss"
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 20                 # 参与背调的公司数
    job_limit: int = 50             # 参与适配度的岗位数
    enable_crawl: bool = True
    enable_backduty: bool = True
    enable_company_score: bool = True
    enable_job_fit: bool = True
    enable_resume: bool = False
    resume: dict[str, Any] | None = None
    no_browser: bool = False
    state_root: str = ".state/login"

    def to_dict(self) -> dict:
        data = dict(self.__dict__)
        data["platforms"] = list(self.platforms)
        data.pop("resume", None)      # 简历内容不进运行记录
        return data


class Pipeline:
    """把各段串起来。没配 http/browser 也能跑（评分段完全离线）。"""

    def __init__(self, store: AppStore, options: Options, *, ctx: AgentContext | None = None,
                 emit: Emit | None = None) -> None:
        self.store = store
        self.options = options
        self.emit = emit or (lambda event: None)
        self.ctx = ctx or AgentContext()
        self.summary: dict[str, Any] = {}

    # ------------------------------------------------------------------ 入口
    async def run(self) -> dict:
        run_id = self.store.start_run(self.options.to_dict())
        self.ctx.options.update({
            "store": self.store,
            "run_id": run_id,
            "state": self.options.state_root,
            "no_browser": self.options.no_browser,
            "log_dir": ".state/logs",
        })
        status = "done"
        try:
            if self.options.enable_crawl:
                await self.stage_crawl()
            if self.options.enable_backduty:
                await self.stage_backduty(run_id)
            if self.options.enable_company_score:
                await self.stage_company_score(run_id)
            if self.options.enable_job_fit:
                await self.stage_job_fit(run_id)
            if self.options.enable_resume:
                await self.stage_resume(run_id)
        except Exception as exc:  # noqa: BLE001 - 出错也要把 run 收尾
            status = "failed"
            self.summary["error"] = f"{type(exc).__name__}: {exc}"
            self.emit({"type": "error", "message": self.summary["error"]})
        finally:
            self.store.finish_run(run_id, status, self.summary)
        self.emit({"type": "done", "ok": status == "done", "run_id": run_id,
                   "summary": self.summary})
        return {"run_id": run_id, "status": status, "summary": self.summary}

    # ------------------------------------------------------------------ 阶段
    async def stage_crawl(self) -> None:
        self.emit({"type": "step", "name": "crawl", "status": "running"})
        result = await sources.run_source(self.options.source, self.options.filters,
                                          emit=self.emit)
        self.summary["crawl"] = {"ok": bool(result.get("ok")),
                                 "reason": result.get("reason")}
        self.emit({"type": "step", "name": "crawl",
                   "status": "done" if result.get("ok") else "skipped",
                   "detail": result.get("reason") or "岗位已入库"})

    async def stage_backduty(self, run_id: int) -> None:
        companies = self.store.company_targets(limit=self.options.limit)
        done = 0
        evidence_total = 0
        for index, company in enumerate(companies, start=1):
            name = str(company.get("company_name") or company.get("company_key") or "")
            key = str(company.get("company_key") or name)
            if not name:
                continue
            for platform in self.options.platforms:
                agent_name = PLATFORM_AGENTS.get(platform)
                if agent_name is None:
                    self._warn(platform, f"没有对应 {platform} 的背调 agent，已跳过")
                    continue
                self.emit({"type": "progress", "name": f"backduty:{platform}",
                           "current": index, "total": len(companies), "message": name})
                result = await self._run_agent(agent_name, AgentRequest(
                    company_name=name, company_key=key))
                if result is None:
                    continue
                if result.findings:
                    evidence_total += self.store.save_evidence(
                        key, agent_name, result.findings, run_id=run_id)
                if result.status.value in ("blocked", "failed", "empty"):
                    self.emit({"type": "error", "agent": agent_name,
                               "message": result.error or "；".join(result.notes[:1])})
            done += 1
        self.summary["companies"] = done
        self.summary["evidence"] = evidence_total
        self.emit({"type": "step", "name": "backduty", "status": "done",
                   "detail": f"{done} 家公司，证据 {evidence_total} 条"})

    async def stage_company_score(self, run_id: int) -> None:
        companies = self.store.company_targets(limit=self.options.limit)
        scored = 0
        for company in companies:
            name = str(company.get("company_name") or "")
            key = str(company.get("company_key") or name)
            if not name:
                continue
            request = self._company_request(key, name)
            result = await self._run_agent("company_score", request)
            if result is None or result.score is None:
                continue
            self.store.save_company_score(key, result.score, run_id=run_id,
                                          extra=result.meta)
            scored += 1
            self.emit({"type": "progress", "name": "company_score",
                       "current": scored, "total": len(companies),
                       "message": f"{name} {result.score.total:.1f}"})
        self.summary["scores"] = scored
        self.emit({"type": "step", "name": "company_score", "status": "done",
                   "detail": f"{scored} 家公司已打分"})

    async def stage_job_fit(self, run_id: int) -> None:
        resume = self.options.resume or self.store.latest_resume(confirmed_only=True)
        if not resume:
            self.summary["fits"] = 0
            self.emit({"type": "step", "name": "job_fit", "status": "skipped",
                       "detail": "还没有已确认的简历，跳过适配度"})
            return
        content = _resume_content(resume)
        resume_id = resume.get("id") if isinstance(resume, dict) else None
        jobs = self.store.jobs_for_fit(limit=self.options.job_limit)
        fitted = 0
        for index, job in enumerate(jobs, start=1):
            request = AgentRequest(company_name=str(job.get("company_name") or ""),
                                   resume=content or {}, job=job)
            result = await self._run_agent("job_fit", request)
            if result is None or result.score is None:
                continue
            self.store.save_job_fit(str(job["job_id"]), result.score,
                                    resume_id=resume_id, run_id=run_id)
            fitted += 1
            self.emit({"type": "progress", "name": "job_fit", "current": index,
                       "total": len(jobs), "message": str(job.get("title") or "")})
        self.summary["fits"] = fitted
        self.emit({"type": "step", "name": "job_fit", "status": "done",
                   "detail": f"{fitted} 个岗位已算适配度"})

    async def stage_resume(self, run_id: int) -> None:
        resume = self.options.resume or self.store.latest_resume(confirmed_only=True)
        if not resume:
            self.emit({"type": "step", "name": "resume", "status": "skipped",
                       "detail": "没有简历，跳过定向简历"})
            return
        content = _resume_content(resume)
        job = self.options.filters.get("job") if isinstance(self.options.filters, dict) else None
        result = await self._run_agent("resume_tailor", AgentRequest(
            resume=content, job=job or {},
            company_name=str(self.options.filters.get("query") or "")))
        self.summary["resume"] = {
            "ok": bool(result and result.usable),
            "status": result.status.value if result else "skipped",
        }
        if result is not None and result.usable:
            meta = result.meta or {}
            answers = list(meta.get("answers") or [])
            try:
                resume_id = self.store.save_resume(
                    dict(meta.get("resume") or {}),
                    name=str((meta.get("resume") or {}).get("name") or "定向简历"),
                    job_id=str((self.options.filters or {}).get("job_id") or "") or None,
                    questions=meta.get("questions"),
                    answers=answers,
                    # 只有用户真的回答过才算"已确认"；否则只是草稿
                    confirmed=bool(answers),
                )
                self.summary["resume"]["resume_id"] = resume_id
                self.summary["resume"]["confirmed"] = bool(answers)
            except Exception as exc:  # noqa: BLE001 - 存不下也要把结果带回去
                self.summary["resume"]["error"] = f"{type(exc).__name__}: {exc}"
        self.emit({"type": "step", "name": "resume",
                   "status": "done" if result and result.usable else "skipped",
                   "detail": "定向简历已生成" if result and result.usable else "定向简历未产出"})

    # ------------------------------------------------------------------ 组装
    def _company_request(self, company_key: str, name: str) -> AgentRequest:
        findings = [_finding_of(row) for row in self.store.evidence_for(company_key)]
        raw = self.store.get_raw(company_key, "tianyancha_web") or {}
        profile = raw.get("profile") if isinstance(raw, dict) else {}
        counts = raw.get("counts") if isinstance(raw, dict) else {}
        risks = raw.get("risks") if isinstance(raw, dict) else []
        return AgentRequest(
            company_name=name,
            company_key=company_key,
            findings=findings,
            metrics={
                "profile": profile or {},
                "counts": counts or {},
                "risks": risks or [],
                "jobs_summary": self.store.jobs_summary(company_key),
            },
        )

    async def _run_agent(self, name: str, request: AgentRequest):
        try:
            agent = get(name)()
        except KeyError:
            self._warn(name, f"agent {name} 不存在，已跳过")
            return None
        try:
            return await agent.execute(request, self.ctx)
        except Exception as exc:  # noqa: BLE001 - 单个 agent 崩了不该中断整条流水线
            self.emit({"type": "error", "agent": name,
                       "message": f"{type(exc).__name__}: {exc}"})
            return None

    def _warn(self, name: str, message: str) -> None:
        self.emit({"type": "warn", "name": name, "message": message})
        try:
            self.store.log_event(agent=name, message=message, level="warn",
                                 code="skipped", run_id=self.ctx.option("run_id"))
        except Exception:  # noqa: BLE001
            pass


def _resume_content(resume: Any) -> dict:
    """简历有两种形态：库里的行（``{"content": {...}}``）或直接传的内容。"""
    if not isinstance(resume, dict):
        return {}
    inner = resume.get("content")
    if isinstance(inner, dict) and inner:
        return inner
    return resume


def _finding_of(row: dict) -> Finding:
    """把库里的证据行还原成 Finding（评分 agent 只认 Finding）。"""
    published = row.get("published_at")
    return Finding(
        source=str(row.get("agent") or row.get("source") or ""),
        title=str(row.get("title") or ""),
        url=str(row.get("url") or ""),
        snippet=str(row.get("snippet") or ""),
        published_at=published if isinstance(published, str) else None,
        author=row.get("author"),
        sentiment=row.get("sentiment"),
        weight=row.get("weight") or 1.0,
        meta=row.get("payload") or {},
    )


async def run_pipeline(store: AppStore, options: Options, *,
                       ctx: AgentContext | None = None,
                       emit: Emit | None = None) -> dict:
    return await Pipeline(store, options, ctx=ctx, emit=emit).run()
