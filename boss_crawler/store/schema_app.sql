-- 应用层（求职背调工作台）新增表。
-- 与采集层 schema.py（jobs/companies/tyc_*）并存，互不覆盖。
-- 本文件是 app/001 基线，全部用 IF NOT EXISTS，可以反复执行；
-- 后续增量改动用新的迁移版本登记，不要直接修改已发布的基线语义。

-- 一次完整流水线的运行记录（前端「运行」页签用它做历史）
CREATE TABLE IF NOT EXISTS public.app_run (
    id            bigserial PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text,                     -- running / done / failed / stopped
    options       jsonb,                    -- 当时的开关与筛选条件
    summary       jsonb                     -- 各家产出条数
);

-- 背调证据：一个 company_key 下、某个 agent 抓到的每一条
CREATE TABLE IF NOT EXISTS public.backduty_evidence (
    id            bigserial PRIMARY KEY,
    company_key   text NOT NULL,
    run_id        bigint REFERENCES public.app_run(id) ON DELETE SET NULL,
    agent         text NOT NULL,
    source        text,
    title         text,
    url           text,
    snippet       text,
    published_at  date,
    author        text,
    sentiment     real,
    weight        real,
    payload       jsonb,
    dedupe_key    text NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now()
);

-- 旧库迁移：去重键最初不含 company_key，同一 URL 会在公司之间互相覆盖。
-- 用命名唯一索引承载 ON CONFLICT (company_key, dedupe_key)。
ALTER TABLE public.backduty_evidence
    DROP CONSTRAINT IF EXISTS backduty_evidence_dedupe_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS backduty_evidence_company_dedupe_uidx
    ON public.backduty_evidence (company_key, dedupe_key);

CREATE INDEX IF NOT EXISTS backduty_evidence_company_idx
    ON public.backduty_evidence (company_key, agent);
CREATE INDEX IF NOT EXISTS backduty_evidence_sentiment_idx
    ON public.backduty_evidence (company_key, sentiment);

-- 天眼查这类"不总结、直接存原数据"的 agent 落在这里
CREATE TABLE IF NOT EXISTS public.backduty_raw (
    company_key   text NOT NULL,
    agent         text NOT NULL,
    run_id        bigint REFERENCES public.app_run(id) ON DELETE SET NULL,
    payload       jsonb NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_key, agent)
);

-- AI agent 对证据的结构化摘要（每个公司每个 agent 保留最新一份）
CREATE TABLE IF NOT EXISTS public.backduty_summary (
    company_key   text NOT NULL,
    agent         text NOT NULL,
    run_id        bigint REFERENCES public.app_run(id) ON DELETE SET NULL,
    summary       jsonb NOT NULL,           -- {summary, points[{topic,text,evidence}], risk_level}
    evidence_count integer,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_key, agent)
);

-- 公司打分（每次一份，保留历史便于对比）
CREATE TABLE IF NOT EXISTS public.company_score (
    id            bigserial PRIMARY KEY,
    company_key   text NOT NULL,
    run_id        bigint REFERENCES public.app_run(id) ON DELETE SET NULL,
    total         real,
    grade         text,
    verdict       text,
    dimensions    jsonb,                    -- [{"name":"风险","score":80,"weight":3,"reason":"..."}]
    advice        jsonb,
    notes         jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- 劳务派遣：独立字段，不进五维。
-- NULL = 信息不足无法判断（不要当 false 用）
ALTER TABLE public.company_score
    ADD COLUMN IF NOT EXISTS is_labor_dispatch boolean;
ALTER TABLE public.company_score
    ADD COLUMN IF NOT EXISTS labor_dispatch_reason text;
ALTER TABLE public.company_score
    ADD COLUMN IF NOT EXISTS labor_dispatch_evidence jsonb;

CREATE INDEX IF NOT EXISTS company_score_key_idx
    ON public.company_score (company_key, created_at DESC);

-- 岗位适配度
CREATE TABLE IF NOT EXISTS public.job_fit (
    id            bigserial PRIMARY KEY,
    job_id        text NOT NULL,
    resume_id     bigint,
    run_id        bigint REFERENCES public.app_run(id) ON DELETE SET NULL,
    total         real,
    grade         text,
    verdict       text,
    dimensions    jsonb,
    advice        jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS job_fit_job_idx
    ON public.job_fit (job_id, created_at DESC);

-- 定向简历版本（用户确认后落库，可追溯父版本）
CREATE TABLE IF NOT EXISTS public.resume_version (
    id            bigserial PRIMARY KEY,
    name          text,
    job_id        text,
    parent_id     bigint REFERENCES public.resume_version(id) ON DELETE SET NULL,
    content       jsonb NOT NULL,
    questions     jsonb,                    -- 当时问用户的问题
    answers       jsonb,                    -- 用户的回答
    confirmed     boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- 报错与"缺失数据/失败原因"日志（每个 agent 都必须写）
CREATE TABLE IF NOT EXISTS public.agent_error (
    id            bigserial PRIMARY KEY,
    run_id        bigint REFERENCES public.app_run(id) ON DELETE SET NULL,
    agent         text,
    tool          text,
    level         text NOT NULL DEFAULT 'error',   -- error / warn / info
    status        text,                            -- blocked / failed / empty / partial
    code          text,                            -- 机器可读的原因码
    message       text,
    context       jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_error_run_idx
    ON public.agent_error (run_id, created_at DESC);

-- 平台登录态登记（前端「初始化」页签用）
CREATE TABLE IF NOT EXISTS public.platform_login (
    platform      text PRIMARY KEY,
    state_dir     text,
    ok            boolean NOT NULL DEFAULT false,
    detail        text,
    updated_at    timestamptz NOT NULL DEFAULT now()
);
