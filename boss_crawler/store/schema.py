"""数据库表结构：建表 DDL 与列定义（唯一的表结构事实来源）。

改表结构只改这里：``db-init`` 会执行 ``SCHEMA_SQL``（全部语句幂等，可重复执行），
仓储层按 ``JOB_COLUMNS`` / ``COMPANY_COLUMNS`` 决定写哪些列。

设计要点：

* ``jobs`` / ``companies`` 各自带 ``embedding`` 与 ``embedding_model``、
  ``embedding_dim``、``embedding_hash``、``embedding_text`` 等列，
  **元数据与向量在同一行**，不做跨表 join 才能取到向量；
* ``embedding_hash`` 是向量化原文的指纹，重复执行 ``embed`` 只补缺失/变更的行；
* JD 结构化字段（职责/要求/年限/学历/工时…）与技能、福利都是独立列或独立表；
* 本机没有 pgvector 扩展时用 ``real[]`` + ``cosine_similarity`` 函数；
  检测到 ``vector`` 扩展时会自动加 ``vector`` 列与 HNSW 索引。
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    company_key     text PRIMARY KEY,
    company_name    text NOT NULL,
    legal_name      text,
    is_anonymous    boolean NOT NULL DEFAULT false,
    is_truncated    boolean NOT NULL DEFAULT false,
    industry        text,
    industry_code   integer,
    scale           text,
    stage           text,
    intro           text,
    job_count       integer NOT NULL DEFAULT 0,
    cities          text[],
    addresses       text[],
    address_source  text,
    salary_min      integer,
    salary_max      integer,
    sample_titles   text[],
    embedding       real[],
    embedding_model text,
    embedding_dim   integer,
    embedding_hash  text,
    embedded_at     timestamptz,
    embed_text      text,
    raw             jsonb,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id           text PRIMARY KEY,
    title            text NOT NULL,
    company_key      text REFERENCES companies(company_key) ON DELETE SET NULL,
    company_name     text,
    legal_name       text,
    salary           text,
    salary_min       integer,
    salary_max       integer,
    salary_unit      text,
    experience       text,
    degree           text,
    city             text,
    district         text,
    business_district text,
    address_detail   text,
    address_full     text,
    address_source   text,
    industry         text,
    industry_code    integer,
    skills           text[],
    welfare          text[],
    description      text,
    url              text,
    source_file      text,
    embedding        real[],
    embedding_model  text,
    embedding_dim    integer,
    embedding_hash   text,
    embedded_at      timestamptz,
    embed_text       text,
    raw              jsonb,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_company_key_idx ON jobs (company_key);
CREATE INDEX IF NOT EXISTS jobs_city_idx ON jobs (city);
CREATE INDEX IF NOT EXISTS jobs_embedding_hash_idx ON jobs (embedding_hash);
CREATE INDEX IF NOT EXISTS companies_embedding_hash_idx ON companies (embedding_hash);

-- JD 结构化列（对已有库可重复执行）
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS responsibilities text[];
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS requirements    text[];
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS jd_sections     jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS jd_skills       text[];
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS jd_benefits     text[];
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS min_years       integer;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS max_years       integer;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS degree_required text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hiring_count    integer;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_schedule   text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS seniority       text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS has_jd          boolean;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS jd_length       integer;

-- 技能 / 福利维度表：把 JD 里的技能变成可 join 的结构化实体
CREATE TABLE IF NOT EXISTS skills (
    name     text PRIMARY KEY,
    category text
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id text NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    skill  text NOT NULL REFERENCES skills(name) ON DELETE CASCADE,
    source text,
    PRIMARY KEY (job_id, skill)
);

CREATE TABLE IF NOT EXISTS benefits (
    name text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS job_benefits (
    job_id  text NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    benefit text NOT NULL REFERENCES benefits(name) ON DELETE CASCADE,
    PRIMARY KEY (job_id, benefit)
);

CREATE INDEX IF NOT EXISTS job_skills_skill_idx ON job_skills (skill);
CREATE INDEX IF NOT EXISTS job_benefits_benefit_idx ON job_benefits (benefit);

-- 向量化批次台账，便于追溯模型/维度/时间
CREATE TABLE IF NOT EXISTS embedding_runs (
    id            bigserial PRIMARY KEY,
    owner_type    text NOT NULL,
    model         text NOT NULL,
    dim           integer,
    item_count    integer NOT NULL,
    prompt_tokens integer,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    note          text
);

-- 无 pgvector 时的余弦相似度（real[] 存储）
CREATE OR REPLACE FUNCTION cosine_similarity(a real[], b real[])
RETURNS double precision AS $$
DECLARE
    i integer;
    dot double precision := 0;
    norm_a double precision := 0;
    norm_b double precision := 0;
BEGIN
    IF a IS NULL OR b IS NULL THEN
        RETURN NULL;
    END IF;
    IF array_length(a, 1) IS DISTINCT FROM array_length(b, 1) THEN
        RETURN NULL;
    END IF;
    FOR i IN 1..array_length(a, 1) LOOP
        dot := dot + a[i] * b[i];
        norm_a := norm_a + a[i] * a[i];
        norm_b := norm_b + b[i] * b[i];
    END LOOP;
    IF norm_a = 0 OR norm_b = 0 THEN
        RETURN 0;
    END IF;
    RETURN dot / (sqrt(norm_a) * sqrt(norm_b));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 元数据 + 向量状态视图
CREATE OR REPLACE VIEW job_vector_status AS
SELECT job_id, title, company_name, city, address_full, salary, experience, degree,
       embedding_model, embedding_dim, embedded_at,
       (embedding IS NOT NULL) AS has_embedding
FROM jobs;

CREATE OR REPLACE VIEW company_vector_status AS
SELECT company_key, company_name, legal_name, industry, job_count, address_source,
       embedding_model, embedding_dim, embedded_at,
       (embedding IS NOT NULL) AS has_embedding
FROM companies;

-- ---------------------------------------------------------------------------
-- 天眼查背调（由 providers/ 写入）
-- 与业务表用 company_key 关联；关联方用天眼查 tyc_id 标识，
-- 因为母公司/子公司未必在我们自己抓取的 54 家里。
-- ---------------------------------------------------------------------------

-- 工商档案：每一家一行，原始返回整份留在 raw 里便于回溯
CREATE TABLE IF NOT EXISTS tyc_company (
    company_key      text PRIMARY KEY REFERENCES companies (company_key) ON DELETE CASCADE,
    tyc_id           bigint,
    credit_code      text,
    name             text,
    legal_person     text,
    reg_status       text,
    reg_capital      text,
    estiblish_time   text,
    reg_location     text,
    industry         text,
    business_scope   text,
    phone            text,
    email            text,
    website          text,
    staff_num        integer,
    company_org_type text,
    match_score      real,          -- 名称匹配分 0~1，偏低说明可能不是同一家
    match_note       text,
    raw              jsonb,
    fetched_at       timestamptz NOT NULL DEFAULT now()
);

-- 关系边：from_key 指向 tyc_company；to_* 是天眼查侧实体
CREATE TABLE IF NOT EXISTS tyc_relation (
    id             bigserial PRIMARY KEY,
    from_key       text NOT NULL,
    relation       text NOT NULL,   -- parent | subsidiary | branch
    to_tyc_id      bigint,
    to_name        text NOT NULL,
    to_credit_code text,
    to_reg_status  text,
    percent        real,            -- 持股比例（总公司/分支为 NULL）
    grade          text,            -- 全资/控股/参股/财务投资/总公司/分支机构
    depth          integer NOT NULL DEFAULT 1,
    via_key        text,            -- 经由哪个上级实体查到
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (from_key, relation, to_name, via_key)
);

-- 风险事件：entity_key 可以是我们的 company_key，也可以是关联方的 tyc_id
CREATE TABLE IF NOT EXISTS tyc_risk (
    id          bigserial PRIMARY KEY,
    entity_key  text NOT NULL,
    entity_name text,
    related_key text,               -- 归属到哪个主体名下
    relation    text,               -- self | parent | subsidiary
    risk_type   text NOT NULL,      -- dishonest | zhixing | abnormal | illegal | punish
    occurred_at text,
    department  text,
    reason      text,
    removed_at  text,
    detail      jsonb,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

-- 调用留痕：核对花费、定位需要重跑的接口
CREATE TABLE IF NOT EXISTS tyc_fetch_log (
    id          bigserial PRIMARY KEY,
    company_key text,
    api         text NOT NULL,
    keyword     text,
    error_code  integer,
    http_status integer,
    elapsed_ms  integer,
    price       real,
    ok          boolean NOT NULL DEFAULT true,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tyc_company_credit ON tyc_company (credit_code);
CREATE INDEX IF NOT EXISTS idx_tyc_relation_from ON tyc_relation (from_key);
CREATE INDEX IF NOT EXISTS idx_tyc_relation_to ON tyc_relation (to_tyc_id);
CREATE INDEX IF NOT EXISTS idx_tyc_risk_entity ON tyc_risk (entity_key);
CREATE INDEX IF NOT EXISTS idx_tyc_risk_related ON tyc_risk (related_key);

-- 背调总览：一家公司一行，含自身与关联方风险计数
CREATE OR REPLACE VIEW tyc_dd_overview AS
SELECT c.company_key,
       c.company_name,
       t.tyc_id,
       t.credit_code,
       t.legal_person,
       t.reg_status,
       t.reg_capital,
       t.staff_num,
       t.match_score,
       (SELECT count(*) FROM tyc_relation r WHERE r.from_key = c.company_key AND r.relation = 'parent') AS parent_cnt,
       (SELECT count(*) FROM tyc_relation r WHERE r.from_key = c.company_key AND r.relation = 'subsidiary') AS subs_cnt,
       (SELECT count(*) FROM tyc_risk k WHERE k.related_key = c.company_key AND k.relation = 'self') AS self_risks,
       (SELECT count(*) FROM tyc_risk k WHERE k.related_key = c.company_key AND k.relation = 'parent') AS parent_risks,
       (SELECT count(*) FROM tyc_risk k WHERE k.related_key = c.company_key AND k.relation = 'subsidiary') AS subs_risks,
       t.fetched_at
FROM companies c
JOIN tyc_company t ON t.company_key = c.company_key;
"""

JOB_COLUMNS = [
    "job_id", "title", "company_key", "company_name", "legal_name", "salary",
    "salary_min", "salary_max", "salary_unit", "experience", "degree", "city",
    "district", "business_district", "address_detail", "address_full",
    "address_source", "industry", "industry_code", "skills", "welfare",
    "description", "url", "source_file",
    # ---- JD 结构化字段 ----
    "responsibilities", "requirements", "jd_sections", "jd_skills", "jd_benefits",
    "min_years", "max_years", "degree_required", "hiring_count", "work_schedule",
    "seniority", "has_jd", "jd_length",
    "raw",
]

COMPANY_COLUMNS = [
    "company_key", "company_name", "legal_name", "is_anonymous", "is_truncated",
    "industry", "industry_code", "scale", "stage", "intro", "job_count", "cities",
    "addresses", "address_source", "salary_min", "salary_max", "sample_titles", "raw",
]
