--
-- PostgreSQL database dump
--

\restrict N26sm6aTCAF6jclUk6zYQCzoDBt1c4c9Sgq0LjLZExbYb0GEGqhv4bU1syx0hbn

-- Dumped from database version 18.1
-- Dumped by pg_dump version 18.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: cosine_similarity(real[], real[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cosine_similarity(a real[], b real[]) RETURNS double precision
    LANGUAGE plpgsql IMMUTABLE
    AS $$
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
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: benefits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.benefits (
    name text NOT NULL
);


--
-- Name: companies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.companies (
    company_key text NOT NULL,
    company_name text NOT NULL,
    legal_name text,
    is_anonymous boolean DEFAULT false NOT NULL,
    is_truncated boolean DEFAULT false NOT NULL,
    industry text,
    industry_code integer,
    scale text,
    stage text,
    intro text,
    job_count integer DEFAULT 0 NOT NULL,
    cities text[],
    addresses text[],
    address_source text,
    salary_min integer,
    salary_max integer,
    sample_titles text[],
    embedding real[],
    embedding_model text,
    embedding_dim integer,
    embedding_hash text,
    embedded_at timestamp with time zone,
    embed_text text,
    raw jsonb,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: company_vector_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.company_vector_status AS
 SELECT company_key,
    company_name,
    legal_name,
    industry,
    job_count,
    address_source,
    embedding_model,
    embedding_dim,
    embedded_at,
    (embedding IS NOT NULL) AS has_embedding
   FROM public.companies;


--
-- Name: embedding_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.embedding_runs (
    id bigint NOT NULL,
    owner_type text NOT NULL,
    model text NOT NULL,
    dim integer,
    item_count integer NOT NULL,
    prompt_tokens integer,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    note text
);


--
-- Name: embedding_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.embedding_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: embedding_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.embedding_runs_id_seq OWNED BY public.embedding_runs.id;


--
-- Name: job_benefits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_benefits (
    job_id text NOT NULL,
    benefit text NOT NULL
);


--
-- Name: job_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_skills (
    job_id text NOT NULL,
    skill text NOT NULL,
    source text
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    job_id text NOT NULL,
    title text NOT NULL,
    company_key text,
    company_name text,
    legal_name text,
    salary text,
    salary_min integer,
    salary_max integer,
    salary_unit text,
    experience text,
    degree text,
    city text,
    district text,
    business_district text,
    address_detail text,
    address_full text,
    address_source text,
    industry text,
    industry_code integer,
    skills text[],
    welfare text[],
    description text,
    url text,
    source_file text,
    embedding real[],
    embedding_model text,
    embedding_dim integer,
    embedding_hash text,
    embedded_at timestamp with time zone,
    embed_text text,
    raw jsonb,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    responsibilities text[],
    requirements text[],
    jd_sections jsonb,
    jd_skills text[],
    jd_benefits text[],
    min_years integer,
    max_years integer,
    degree_required text,
    hiring_count integer,
    work_schedule text,
    seniority text,
    has_jd boolean,
    jd_length integer
);


--
-- Name: job_vector_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.job_vector_status AS
 SELECT job_id,
    title,
    company_name,
    city,
    address_full,
    salary,
    experience,
    degree,
    embedding_model,
    embedding_dim,
    embedded_at,
    (embedding IS NOT NULL) AS has_embedding
   FROM public.jobs;


--
-- Name: skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills (
    name text NOT NULL,
    category text
);


--
-- Name: tyc_company; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tyc_company (
    company_key text NOT NULL,
    tyc_id bigint,
    credit_code text,
    name text,
    legal_person text,
    reg_status text,
    reg_capital text,
    estiblish_time text,
    reg_location text,
    industry text,
    business_scope text,
    phone text,
    email text,
    website text,
    staff_num integer,
    company_org_type text,
    match_score real,
    match_note text,
    raw jsonb,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tyc_relation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tyc_relation (
    id bigint NOT NULL,
    from_key text NOT NULL,
    relation text NOT NULL,
    to_tyc_id bigint,
    to_name text NOT NULL,
    to_credit_code text,
    to_reg_status text,
    percent real,
    grade text,
    depth integer DEFAULT 1 NOT NULL,
    via_key text,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tyc_risk; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tyc_risk (
    id bigint NOT NULL,
    entity_key text NOT NULL,
    entity_name text,
    related_key text,
    relation text,
    risk_type text NOT NULL,
    occurred_at text,
    department text,
    reason text,
    removed_at text,
    detail jsonb,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tyc_dd_overview; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.tyc_dd_overview AS
 SELECT c.company_key,
    c.company_name,
    t.tyc_id,
    t.credit_code,
    t.legal_person,
    t.reg_status,
    t.reg_capital,
    t.staff_num,
    t.match_score,
    ( SELECT count(*) AS count
           FROM public.tyc_relation r
          WHERE ((r.from_key = c.company_key) AND (r.relation = 'parent'::text))) AS parent_cnt,
    ( SELECT count(*) AS count
           FROM public.tyc_relation r
          WHERE ((r.from_key = c.company_key) AND (r.relation = 'subsidiary'::text))) AS subs_cnt,
    ( SELECT count(*) AS count
           FROM public.tyc_risk k
          WHERE ((k.related_key = c.company_key) AND (k.relation = 'self'::text))) AS self_risks,
    ( SELECT count(*) AS count
           FROM public.tyc_risk k
          WHERE ((k.related_key = c.company_key) AND (k.relation = 'parent'::text))) AS parent_risks,
    ( SELECT count(*) AS count
           FROM public.tyc_risk k
          WHERE ((k.related_key = c.company_key) AND (k.relation = 'subsidiary'::text))) AS subs_risks,
    t.fetched_at
   FROM (public.companies c
     JOIN public.tyc_company t ON ((t.company_key = c.company_key)));


--
-- Name: tyc_fetch_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tyc_fetch_log (
    id bigint NOT NULL,
    company_key text,
    api text NOT NULL,
    keyword text,
    error_code integer,
    http_status integer,
    elapsed_ms integer,
    price real,
    ok boolean DEFAULT true NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tyc_fetch_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tyc_fetch_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tyc_fetch_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tyc_fetch_log_id_seq OWNED BY public.tyc_fetch_log.id;


--
-- Name: tyc_relation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tyc_relation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tyc_relation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tyc_relation_id_seq OWNED BY public.tyc_relation.id;


--
-- Name: tyc_risk_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tyc_risk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tyc_risk_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tyc_risk_id_seq OWNED BY public.tyc_risk.id;


--
-- Name: embedding_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embedding_runs ALTER COLUMN id SET DEFAULT nextval('public.embedding_runs_id_seq'::regclass);


--
-- Name: tyc_fetch_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_fetch_log ALTER COLUMN id SET DEFAULT nextval('public.tyc_fetch_log_id_seq'::regclass);


--
-- Name: tyc_relation id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_relation ALTER COLUMN id SET DEFAULT nextval('public.tyc_relation_id_seq'::regclass);


--
-- Name: tyc_risk id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_risk ALTER COLUMN id SET DEFAULT nextval('public.tyc_risk_id_seq'::regclass);


--
-- Name: benefits benefits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benefits
    ADD CONSTRAINT benefits_pkey PRIMARY KEY (name);


--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (company_key);


--
-- Name: embedding_runs embedding_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embedding_runs
    ADD CONSTRAINT embedding_runs_pkey PRIMARY KEY (id);


--
-- Name: job_benefits job_benefits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_pkey PRIMARY KEY (job_id, benefit);


--
-- Name: job_skills job_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_pkey PRIMARY KEY (job_id, skill);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (job_id);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (name);


--
-- Name: tyc_company tyc_company_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_company
    ADD CONSTRAINT tyc_company_pkey PRIMARY KEY (company_key);


--
-- Name: tyc_fetch_log tyc_fetch_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_fetch_log
    ADD CONSTRAINT tyc_fetch_log_pkey PRIMARY KEY (id);


--
-- Name: tyc_relation tyc_relation_from_key_relation_to_name_via_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_relation
    ADD CONSTRAINT tyc_relation_from_key_relation_to_name_via_key_key UNIQUE (from_key, relation, to_name, via_key);


--
-- Name: tyc_relation tyc_relation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_relation
    ADD CONSTRAINT tyc_relation_pkey PRIMARY KEY (id);


--
-- Name: tyc_risk tyc_risk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_risk
    ADD CONSTRAINT tyc_risk_pkey PRIMARY KEY (id);


--
-- Name: companies_embedding_hash_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX companies_embedding_hash_idx ON public.companies USING btree (embedding_hash);


--
-- Name: idx_tyc_company_credit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tyc_company_credit ON public.tyc_company USING btree (credit_code);


--
-- Name: idx_tyc_relation_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tyc_relation_from ON public.tyc_relation USING btree (from_key);


--
-- Name: idx_tyc_relation_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tyc_relation_to ON public.tyc_relation USING btree (to_tyc_id);


--
-- Name: idx_tyc_risk_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tyc_risk_entity ON public.tyc_risk USING btree (entity_key);


--
-- Name: idx_tyc_risk_related; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tyc_risk_related ON public.tyc_risk USING btree (related_key);


--
-- Name: job_benefits_benefit_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_benefits_benefit_idx ON public.job_benefits USING btree (benefit);


--
-- Name: job_skills_skill_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX job_skills_skill_idx ON public.job_skills USING btree (skill);


--
-- Name: jobs_city_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_city_idx ON public.jobs USING btree (city);


--
-- Name: jobs_company_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_company_key_idx ON public.jobs USING btree (company_key);


--
-- Name: jobs_embedding_hash_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_embedding_hash_idx ON public.jobs USING btree (embedding_hash);


--
-- Name: job_benefits job_benefits_benefit_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_benefit_fkey FOREIGN KEY (benefit) REFERENCES public.benefits(name) ON DELETE CASCADE;


--
-- Name: job_benefits job_benefits_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_benefits
    ADD CONSTRAINT job_benefits_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;


--
-- Name: job_skills job_skills_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(job_id) ON DELETE CASCADE;


--
-- Name: job_skills job_skills_skill_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_skills
    ADD CONSTRAINT job_skills_skill_fkey FOREIGN KEY (skill) REFERENCES public.skills(name) ON DELETE CASCADE;


--
-- Name: jobs jobs_company_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_company_key_fkey FOREIGN KEY (company_key) REFERENCES public.companies(company_key) ON DELETE SET NULL;


--
-- Name: tyc_company tyc_company_company_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tyc_company
    ADD CONSTRAINT tyc_company_company_key_fkey FOREIGN KEY (company_key) REFERENCES public.companies(company_key) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict N26sm6aTCAF6jclUk6zYQCzoDBt1c4c9Sgq0LjLZExbYb0GEGqhv4bU1syx0hbn

