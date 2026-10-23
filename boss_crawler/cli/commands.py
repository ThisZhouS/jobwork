"""子命令实现：只做编排，具体能力都在 crawl / structuring / store / embedding 里。

每个 ``cmd_*`` 的职责固定为三步：读参数 -> 调用底层能力 -> 打印摘要。
业务逻辑不要写在这里，否则测试和复用都得经过命令行。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from .. import config
from ..crawl import BossBrowser, BrowserUnavailable, JobCrawler, LoginRequired
from ..filters import resolve_filters
from ..store import (
    JobStore,
    expand_inputs,
    load_clean_records,
    load_raw_records,
    merge_record,
)

def _browser(args) -> BossBrowser:
    return BossBrowser(headless=args.headless)


def cmd_login(args) -> int:
    with _browser(args) as browser:
        if browser.is_logged_in(verify=False) and not args.force:
            print("已存在登录态（persistent profile）。如需重新登录请加 --force。")
            return 0
        ok = browser.interactive_login(timeout_s=args.timeout)
    return 0 if ok else 3


def cmd_crawl(args) -> int:
    if args.city not in config.CITY_CODES:
        print(f"未知城市「{args.city}」，可用：{', '.join(config.CITY_CODES)}")
        return 2

    # 先校验筛选参数，避免参数写错还白开一次浏览器
    try:
        resolve_filters(
            salary=args.salary,
            experience=args.experience,
            degree=args.degree,
            industry=args.industry,
        )
    except ValueError as exc:
        print(f"筛选参数错误：{exc}")
        return 2

    name = f"jobs_{args.query}_{args.city}".replace(" ", "-")
    store = JobStore(Path(args.out or config.OUTPUT_DIR), name)

    with _browser(args) as browser:
        if not browser.is_logged_in():
            print("未检测到有效登录态，请先运行：python -m boss_crawler login")
            return 3

        crawler = JobCrawler(
            browser,
            query=args.query,
            city=args.city,
            pages=args.pages,
            with_detail=args.detail,
            take=args.take,
            store=store,
            salary=args.salary,
            experience=args.experience,
            degree=args.degree,
            industry=args.industry,
        )
        started = time.time()
        try:
            crawler.run()
        except LoginRequired as exc:
            print(f"登录态失效：{exc}\n请重新运行：python -m boss_crawler login --force")
            return 3

    jsonl = store.flush()
    csv_path = store.export_csv()
    print(f"\n完成：{store.count} 条职位，用时 {time.time() - started:.0f}s")
    print(f"  JSONL: {jsonl}")
    print(f"  CSV  : {csv_path}")
    return 0


def cmd_doctor(args) -> int:
    import scrapling

    print(f"scrapling: {scrapling.__version__}")
    for module in ("patchright", "browserforge"):
        try:
            __import__(module)
            print(f"{module}: OK")
        except Exception as exc:
            print(f"{module}: 缺失（{exc}）")

    print(f"profile: {config.PROFILE_DIR}")
    with _browser(args) as browser:
        page = browser.page(goto=config.HOME_URL)
        print(f"浏览器: OK  url={page.url[:60]}  stealth={page.evaluate('() => window.__bc_stealth__ || null')}")
        print(f"登录态: {'有效' if browser.is_logged_in() else '缺失/失效'}")
        try:
            payload = crawler_probe(browser)
            print(f"接口: code={payload.get('code')} {payload.get('message')}")
        except Exception as exc:
            print(f"接口: 调用失败（{exc}）")
    return 0


def crawler_probe(browser: BossBrowser) -> dict:
    """用一次列表接口请求验证风控是否放行。"""
    page = browser.page()
    return page.evaluate(
        """async (url) => {
            const r = await fetch(url, {credentials: 'include'});
            try { return await r.json(); } catch (e) { return {code: -1, message: 'non-json'}; }
        }""",
        config.JOB_LIST_API.format(
            query="Python", city=config.CITY_CODES["成都"], page=1, page_size=1
        ),
    )


def cmd_filters(args) -> int:
    from ..filters import FILTERS

    for field, (label, mapping) in FILTERS.items():
        print(f"{label}（--{field}）：")
        print("  " + "、".join(mapping))
        print()
    print("任意一项都可以直接传数字码，例如 --industry 100021、--salary 406。")
    return 0


def cmd_process(args) -> int:
    import csv
    import json

    from ..structuring import build_companies, build_report, clean_record

    inputs = expand_inputs(args.input)
    if not inputs:
        print("没有找到输入文件，请检查 --input（默认 output/*.jsonl）")
        return 2

    raw_records: dict[str, dict] = {}
    for path in inputs:
        count = 0
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if isinstance(record.get("company"), dict):
                    continue  # 已经是清洗后的结构，跳过
                key = record.get("job_id") or f"{record.get('title')}|{record.get('company')}"
                if key in raw_records:
                    merge_record(raw_records[key], record)
                else:
                    raw_records[key] = record
                count += 1
        print(f"读取 {path}：{count} 条")

    records = list(raw_records.values())
    enriched_path = Path(args.out or (config.OUTPUT_DIR / "clean")) / "enriched.jsonl"
    if args.enrich:
        records = _enrich_records(records, limit=args.limit, query=args.query, city=args.city)
        if records is None:
            return 3
        # 补到的详情落盘，后续 process 会自动把它当作输入复用（地址优先保留完整的那份）
        enriched_path.parent.mkdir(parents=True, exist_ok=True)
        with enriched_path.open("w", encoding="utf-8") as fh:
            for record in records:
                if (record.get("address") or "").strip():
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"补详情结果已保存：{enriched_path}")

    jobs = [clean_record(record, source_file=record.get("source_file", "")) for record in records]
    companies = build_companies(jobs)
    report = build_report(jobs, companies)

    out_dir = Path(args.out or (config.OUTPUT_DIR / "clean"))
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs_jsonl = out_dir / "jobs_clean.jsonl"
    with jobs_jsonl.open("w", encoding="utf-8") as fh:
        for job in jobs:
            fh.write(json.dumps(job, ensure_ascii=False) + "\n")

    jobs_csv = out_dir / "jobs_clean.csv"
    with jobs_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "company_name", "legal_name", "is_anonymous", "job_title", "salary",
                "salary_unit", "salary_min", "salary_max", "experience", "degree", "city",
                "district", "business_district", "address_detail", "address_full",
                "address_source", "industry", "url",
            ],
        )
        writer.writeheader()
        for job in jobs:
            company, workplace = job["company"], job["workplace"]
            writer.writerow({
                "company_name": company["name"],
                "legal_name": company["legal_name"],
                "is_anonymous": company["is_anonymous"],
                "job_title": job["title"],
                "salary": job["salary"],
                "salary_unit": job["salary_unit"],
                "salary_min": job["salary_min"],
                "salary_max": job["salary_max"],
                "experience": job["experience"],
                "degree": job["degree"],
                "city": workplace["city"],
                "district": workplace["district"],
                "business_district": workplace["business_district"],
                "address_detail": workplace["detail"],
                "address_full": workplace["full"],
                "address_source": workplace["source"],
                "industry": company["industry"],
                "url": job["url"],
            })

    companies_csv = out_dir / "companies.csv"
    with companies_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "company_name", "legal_name", "is_anonymous", "industry", "industry_code",
                "scale", "stage", "job_count", "cities", "addresses", "address_source",
                "salary_range", "sample_titles",
            ],
        )
        writer.writeheader()
        for company in companies:
            low, high = company["salary_min"], company["salary_max"]
            salary_range = (
                f"{low / 1000:.0f}K-{high / 1000:.0f}K"
                if low is not None and high is not None and low >= 1000 and high >= 1000
                else ""
            )
            writer.writerow({
                **{k: company[k] for k in (
                    "company_name", "legal_name", "is_anonymous", "industry",
                    "industry_code", "scale", "stage", "job_count",
                )},
                "cities": " / ".join(company["cities"]),
                "addresses": " | ".join(company["addresses"]),
                "address_source": company["address_source"],
                "salary_range": salary_range,
                "sample_titles": " / ".join(company["sample_titles"]),
            })

    report_path = out_dir / "clean_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    from ..export import write_workbook

    workbook_path = out_dir / "jobs.xlsx"
    has_xlsx = write_workbook(workbook_path, jobs, companies, report)

    print(f"\n清洗完成：{report['jobs']} 条职位 / {report['companies']} 家公司")
    print(
        f"  地址：完整 {report['address_detail']} 条，派生于城市/商圈 {report['address_derived']} 条，"
        f"缺失 {report['address_missing']} 条"
    )
    print(
        f"  公司：脱敏 {report['anonymous_companies']} 家，截断 {report['truncated_companies']} 家，"
        f"补全工商全称 {report['legal_name_recovered']} 家"
    )
    print(f"  {jobs_jsonl}")
    print(f"  {jobs_csv}")
    print(f"  {companies_csv}")
    if has_xlsx:
        print(f"  {workbook_path}")
    print(f"  {report_path}")
    return 0


def cmd_enrich(args) -> int:
    """回源抓详情，补全 JD / 地址 / 技能 / 福利，合并保存到 enriched.jsonl。"""
    import json

    out_dir = Path(args.out or (config.OUTPUT_DIR / "clean"))
    enriched_file = out_dir / "enriched.jsonl"

    records = load_raw_records(args.input)
    if enriched_file.exists():
        for line in enriched_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            key = record.get("job_id")
            if key in records:
                merge_record(records[key], record)
            elif key:
                records[key] = record

    missing_desc = [r for r in records.values() if not (r.get("description") or "").strip()]
    missing_addr = [r for r in records.values() if not (r.get("address") or "").strip()]
    if args.only == "description":
        targets = missing_desc
    elif args.only == "address":
        targets = missing_addr
    else:
        targets = [r for r in records.values()
                   if not (r.get("description") or "").strip()
                   or not (r.get("address") or "").strip()]
    total = len(targets)
    if args.limit:
        targets = targets[: args.limit]
    print(f"记录 {len(records)} 条：缺 JD {len(missing_desc)}，缺详情地址 {len(missing_addr)}")
    print(f"本轮补详情 {len(targets)} / {total} 条")
    if not targets:
        print("无需补全。")
        return 0

    with BossBrowser(headless=False) as browser:
        if not browser.is_logged_in():
            print("未检测到有效登录态，请先运行：python -m boss_crawler login")
            return 3
        crawler = JobCrawler(browser, query=args.query, city=args.city, pages=1)
        crawler.enrich_records(targets)

    kept = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    with enriched_file.open("w", encoding="utf-8") as fh:
        for record in records.values():
            if (record.get("description") or "").strip() or (record.get("address") or "").strip():
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                kept += 1

    have_desc = sum(1 for r in records.values() if (r.get("description") or "").strip())
    have_addr = sum(1 for r in records.values() if (r.get("address") or "").strip())
    print(f"已保存 {kept} 条到 {enriched_file}")
    print(f"覆盖率：JD {have_desc}/{len(records)}，详情地址 {have_addr}/{len(records)}")
    return 0


def _enrich_records(records: list[dict], *, limit: int | None, query: str, city: str):
    """回源抓详情，补全地址与描述（需要登录态）。"""
    targets = [
        r for r in records
        if r.get("security_id")
        and (not (r.get("address") or "").strip() or not (r.get("description") or "").strip())
    ]
    if not targets:
        print("所有记录都已有地址与 JD，无需回源补详情。")
        return records
    if limit:
        targets = targets[:limit]
    print(f"回源补详情：{len(targets)} 条（共 {len(records)} 条）")

    with BossBrowser(headless=False) as browser:
        if not browser.is_logged_in():
            print("未检测到有效登录态，请先运行：python -m boss_crawler login")
            return None
        crawler = JobCrawler(browser, query=query, city=city, pages=1)
        crawler.enrich_records(targets)
    return records


def _open_db(args):
    from ..store import Database, DatabaseError

    try:
        return Database(
            host=getattr(args, "host", None),
            port=getattr(args, "port", None),
            user=getattr(args, "user", None),
            database=getattr(args, "database", None),
        )
    except DatabaseError as exc:
        print(f"数据库不可用：{exc}")
        return None


def cmd_db_init(args) -> int:
    db = _open_db(args)
    if db is None:
        return 2
    try:
        with db:
            info = db.init_schema()
            stats = db.stats()
    except Exception as exc:
        print(f"建表失败：{exc}")
        return 1
    print(f"数据库 {db.database}@{db.host}:{db.port} 初始化完成")
    print(f"  pgvector 扩展：{'可用' if info['pgvector'] else '不可用（使用 real[] + cosine_similarity 函数）'}")
    if info.get("vector_column"):
        print(f"  vector 列已创建，索引：{info['index']}")
    print(f"  现有数据：{stats['jobs']} 职位 / {stats['companies']} 公司")
    return 0


def cmd_db_load(args) -> int:
    db = _open_db(args)
    if db is None:
        return 2
    jobs, raw_by_id, companies = load_clean_records(args.input)
    if not jobs:
        print("没有读到可入库的记录，请检查 --input")
        return 2
    print(f"准备入库：{len(jobs)} 条职位 / {len(companies)} 家公司")
    try:
        with db:
            db.init_schema()
            raw_by_company = {
                c["key"]: raw_by_id.get(
                    next((j["job_id"] for j in jobs if j["company"]["key"] == c["key"]), ""), {}
                )
                for c in companies
            }
            company_count = db.upsert_companies(companies, raw_by_company)
            job_count = db.upsert_jobs(jobs, raw_by_id)
            stats = db.stats()
    except Exception as exc:
        print(f"入库失败：{exc}")
        return 1
    print(f"写入完成：{company_count} 家公司 / {job_count} 条职位")
    print(f"  库内现有：{stats['jobs']} 职位（已向量化 {stats['jobs_embedded']}）"
          f" / {stats['companies']} 公司（已向量化 {stats['companies_embedded']}）")
    return 0


def cmd_embed(args) -> int:
    from ..embedding import ArkEmbedder, EmbeddingError, company_embedding_text, content_hash, job_embedding_text

    db = _open_db(args)
    if db is None:
        return 2
    owners = ["job", "company"] if args.owner == "all" else [args.owner]

    jobs, _raw, companies = load_clean_records(args.input)
    payloads: dict[str, list[tuple[str, str]]] = {
        "job": [(j["job_id"], job_embedding_text(j)) for j in jobs],
        "company": [(c["key"], company_embedding_text(c)) for c in companies],
    }

    try:
        embedder = ArkEmbedder()
    except EmbeddingError as exc:
        print(f"向量化不可用：{exc}")
        return 2
    print(f"向量化模型：{embedder.model} @ {embedder.base_url}")

    try:
        with db:
            db.init_schema()
            db.has_pgvector()
            for owner in owners:
                pairs = payloads[owner]
                hashes = {owner_id: content_hash(text) for owner_id, text in pairs}
                if args.force:
                    pending = [owner_id for owner_id, _ in pairs]
                else:
                    pending = db.embedding_targets(owner, embedder.model, hashes)
                if args.limit:
                    pending = pending[: args.limit]
                print(f"[{owner}] 待向量化 {len(pending)} / {len(pairs)} 条")
                if not pending:
                    continue
                text_by_id = dict(pairs)
                vectors = embedder.embed([text_by_id[owner_id] for owner_id in pending])
                items = [
                    {
                        "id": owner_id,
                        "content": text_by_id[owner_id],
                        "hash": hashes[owner_id],
                        "vector": vector,
                    }
                    for owner_id, vector in zip(pending, vectors)
                ]
                saved = db.save_embeddings(owner, embedder.model, items)
                db.log_run(owner, embedder.model, embedder.dim, saved, note="cli embed")
                print(f"[{owner}] 已写入 {saved} 条向量，维度 {embedder.dim}")
            stats = db.stats()
    except EmbeddingError as exc:
        print(f"向量化失败：{exc}")
        return 1
    except Exception as exc:
        print(f"向量化过程出错：{exc}")
        return 1

    print(f"完成：职位 {stats['jobs_embedded']}/{stats['jobs']} 已向量化，"
          f"公司 {stats['companies_embedded']}/{stats['companies']} 已向量化")
    return 0


def cmd_search(args) -> int:
    from ..embedding import ArkEmbedder, EmbeddingError

    db = _open_db(args)
    if db is None:
        return 2
    try:
        embedder = ArkEmbedder()
        vector = embedder.embed_one(args.query)
    except EmbeddingError as exc:
        print(f"向量化不可用：{exc}")
        return 2

    with db:
        db.has_pgvector()
        print(f"查询：{args.query}（模型 {embedder.model}，维度 {embedder.dim}）\n")
        if args.owner in {"job", "all"}:
            print(f"—— 最相似的 {args.top} 个岗位 ——")
            for index, row in enumerate(db.search_jobs(vector, args.top), start=1):
                print(
                    f"{index}. [{row['score']:.4f}] {row['title']} @ {row['company_name']}"
                    f" | {row.get('city') or ''}{row.get('district') or ''}"
                    f" | {row.get('salary') or ''} | {row.get('address_full') or ''}"
                )
        if args.owner in {"company", "all"}:
            print(f"\n—— 最相似的 {args.top} 家公司 ——")
            for index, row in enumerate(db.search_companies(vector, args.top), start=1):
                addresses = row.get("addresses") or []
                print(
                    f"{index}. [{row['score']:.4f}] {row['company_name']}"
                    f" | {row.get('industry') or ''} | {' | '.join(addresses[:2])}"
                )
    return 0


def cmd_db_stats(args) -> int:
    db = _open_db(args)
    if db is None:
        return 2
    with db:
        db.has_pgvector()
        stats = db.stats()
    print(f"数据库：{db.database}@{db.host}:{db.port}（{stats['database_size']}）")
    print(f"  pgvector：{'可用' if stats['pgvector'] else '不可用'}")
    print(f"  职位：{stats['jobs']} 条，已向量化 {stats['jobs_embedded']} 条")
    print(f"  公司：{stats['companies']} 条，已向量化 {stats['companies_embedded']} 条")
    if stats["model"]:
        print(f"  向量模型：{stats['model']['embedding_model']}，维度 {stats['model']['embedding_dim']}")
    print(f"  向量化批次：{stats['embedding_runs']} 次")
    return 0


def cmd_dd(args) -> int:
    """天眼查背调：从库里取公司名 -> 查工商/母子关系/风险 -> 写回库。"""
    from ..providers import (
        DueDiligenceOptions,
        TianyanchaClient,
        estimate_cost,
        investigate,
        print_summary,
    )

    db = _open_db(args)
    if db is None:
        return 2

    options = DueDiligenceOptions(
        depth=args.depth,
        max_related=args.max_related,
        min_percent=args.min_percent,
        only_relations=args.only_relations,
        skip_risks=args.skip_risks,
        max_cost=args.max_cost,
    )

    source = getattr(args, "source", "cli")
    with db:
        db.init_schema()
        targets = db.company_targets(include_anonymous=args.include_anonymous, limit=args.limit)
        if not targets:
            print("库里没有可背调的公司，先跑 db-load。")
            return 0

        skipped = "包含" if args.include_anonymous else "已跳过脱敏"
        print(f"待背调公司：{len(targets)} 家（{skipped}）")

        if source == "cli":
            # 免费路线：天眼AI（tyc-cli）免费额度，不走按次计费的开放接口
            print("数据来源：天眼AI CLI（免费额度）")
            if args.dry_run:
                for row in targets[:10]:
                    print(f"  - {row['company_key']}  {row['company_name']}")
                if len(targets) > 10:
                    print(f"  ... 其余 {len(targets) - 10} 家")
                print("\n免费工具：工商登记 / 风险总览 / 简介 / 规模 / 标签 / 知产评分")
                print("拿不到：对外投资、分支、年报、联系方式（属 VIP 工具）")
                return 0
            return _dd_cli(db, targets, args)

        plan = estimate_cost(len(targets), depth=args.depth, max_related=args.max_related)
        print(
            f"预估花费：约 ¥{plan['total']:.2f}"
            f"（每家 ¥{plan['per_company']:.2f} + 关联方 ¥{plan['per_related']:.2f}/家 × {args.max_related}）"
        )
        if args.dry_run:
            for row in targets[:10]:
                print(f"  - {row['company_key']}  {row['company_name']}")
            if len(targets) > 10:
                print(f"  ... 其余 {len(targets) - 10} 家")
            return 0

        client = TianyanchaClient()
        if not client.token:
            print("缺少 token：在 .env 里写 TIANYANCHA_TOKEN=...（或放进 .state/tyc_token.txt）")
            return 3

        engine = getattr(args, "engine", "async")
        if engine == "sync":
            _dd_sync(db, targets, options, client)
        else:
            _dd_async(db, targets, args, client)

        stats = db.tyc_stats()
        print(
            f"\n库内：已背调 {stats['fetched']}/{stats['companies']} 家，"
            f"关系 {stats['relations']} 条，风险 {stats['risks']} 条"
        )
        if stats["risks_by_type"]:
            print("  风险分布：" + "，".join(f"{k} {v}" for k, v in stats["risks_by_type"].items()))
        if stats["subsidiaries_by_grade"]:
            print("  子公司分级：" + "，".join(f"{k} {v}" for k, v in stats["subsidiaries_by_grade"].items()))
    return 0


def _dd_sync(db, targets, options, client) -> None:
    """顺序执行版：一家跑完再跑下一家，便于逐步调试。"""
    from ..providers import investigate, print_summary

    def progress(item) -> None:
        flag = "✓" if item.matched else "×"
        print(
            f"  {flag} {item.company_name[:28]:30} 关系 {item.relations:<3}"
            f" 风险 {item.risks:<3} {item.verdict}"
        )

    print()
    results = investigate(db, targets, options=options, client=client, on_progress=progress)
    db.commit()
    print()
    print_summary(results, cost=client.spent)


def _dd_cli(db, targets, args) -> int:
    """免费路线：用天眼AI（tyc-cli）免费额度写工商档案与风险计数。

    与付费路线的能力差距要说清楚：
    * 免费拿得到：工商登记、风险总览（**计数**）、简介、规模、标签、知产评分；
    * 免费拿不到：对外投资/分支/年报/联系方式等（VIP 工具），以及风险**明细**。

    所以这里只写真有的东西，不拿计数去伪造明细行；关系表一行都不碰，
    免得把之前用付费接口抓到的关系边删掉。
    """
    import time as _time

    from ..providers.relations import parse_profile
    from ..providers.tyc_cli import TycCli, TycCliError

    cli = TycCli()
    try:
        cli.require_installed()
    except TycCliError as exc:
        print(f"{exc}\n安装：npm install -g tyc-cli\n登录：tyc login")
        return 3

    delay = max(1.0, float(getattr(args, "delay", 2.0) or 2.0))
    ok = failed = 0
    total = len(targets)
    print()

    for index, row in enumerate(targets, 1):
        name = row["company_name"]
        key = row["company_key"]
        try:
            bundle = cli.basic_bundle(name)
        except TycCliError as exc:
            if exc.needs_login:
                print(f"\n天眼AI 未登录：{exc}\n先运行：tyc login")
                return 3
            failed += 1
            print(f"  × [{index:>3}/{total}] {name[:30]}  {exc}")
            _time.sleep(delay)
            continue

        registration = _bundle_part(bundle.get("registration"))
        profile = parse_profile(registration) if registration else {}
        db.save_tyc_profile(
            key,
            profile,
            match_score=1.0 if registration else None,
            match_note="tyc-cli 免费额度",
            raw=bundle,
        )

        risk_rows = _risk_rows_from_overview(key, name, _bundle_part(bundle.get("risk")))
        db.replace_tyc_risks(key, risk_rows)
        db.commit()

        ok += 1
        flag = "✓" if profile.get("credit_code") else "◐"
        print(f"  {flag} [{index:>3}/{total}] {name[:30]:32} 风险计数 {len(risk_rows)} 类")

        if index < total:
            _time.sleep(delay)

    print(f"\n完成：成功 {ok} 家，失败 {failed} 家")
    print("提示：免费额度拿不到关系与风险明细；需要这些请用 --source api")
    return 0 if ok else 1


def _bundle_part(value):
    """CLI 返回可能是 {data:{...}} / [{...}] / 裸对象，统一成 dict。"""
    if isinstance(value, dict):
        for key in ("data", "result"):
            inner = value.get(key)
            if isinstance(inner, dict):
                return inner
        return value
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return {}


def _risk_rows_from_overview(company_key: str, company_name: str, overview) -> list[dict]:
    """把风险总览的计数写成"每类一行"的占位记录。

    ``reason`` 里明确写"概览计数、无明细"，避免下游把它当成真实案件。
    """
    if not isinstance(overview, dict):
        return []
    rows: list[dict] = []
    for label, value in overview.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            continue
        rows.append({
            "entity_key": company_key,
            "entity_name": company_name,
            "relation": "self",
            "risk_type": str(label),
            "occurred_at": None,
            "reason": f"免费额度仅提供概览计数：共 {int(value)} 条（无明细）",
        })
    return rows


def _dd_async(db, targets, args, client) -> None:
    """引擎版：队列 + 并发 + 重试 + 统计。"""
    from ..engine import SignalManager
    from ..providers import run_sync

    signals = SignalManager()
    done = {"n": 0}

    async def on_item(**kwargs) -> None:
        item = kwargs.get("item")
        if item is not None and item.item_type == "company_profile":
            done["n"] += 1
            name = item.get("profile", {}).get("name") or item.get("company_name", "")
            print(f"  [{done['n']:>3}] {str(name)[:40]}")

    signals.connect("item_scraped", on_item)

    print(f"引擎：async，并发 {args.concurrency}，间隔 {args.delay}s，重试 {args.retries} 次\n")
    # 用 run_sync 包一层：它内部起事件循环，避免在同步 CLI 里直接 await 协程
    result = run_sync(
        db,
        targets,
        token=client.token,
        concurrency=args.concurrency,
        download_delay=args.delay,
        retry_times=args.retries,
        min_percent=args.min_percent,
        max_related=args.max_related,
        skip_risks=args.skip_risks,
        only_relations=args.only_relations,
        max_cost=args.max_cost,
        log_level="debug" if getattr(args, "verbose", False) else "info",
        signals=signals,
    )
    print()
    for line in result.summary_lines():
        print(line)
    if result.skipped:
        print(f"  未匹配 {len(result.skipped)} 家（可人工复核）：")
        for row in result.skipped[:5]:
            print(f"    - {row['company_key']}：{row['note']}")


# ---------------------------------------------------------------- agents
def _agent_tools(name: str) -> list[str]:
    """看一个 agent 声明了哪些工具（对它没调工具就返回空）。"""
    from ..agents.registry import get

    try:
        agent = get(name)()
    except Exception:  # noqa: BLE001
        return []
    calls = getattr(agent, "tools", ()) or ()
    return [call.tool for call in calls]


def cmd_agents(args) -> int:
    """列出或执行 agent。单独跑一个 / 按顺序串联都由这里承载。"""
    import asyncio
    import json

    from ..agents import AgentContext, AgentKind, AgentRequest, Pipeline, catalog

    if args.action == "list":
        from ..agents.registry import load_errors

        kind = AgentKind(args.kind) if args.kind else None
        rows = catalog(kind)
        errors = load_errors()
        if not rows:
            print("还没有注册任何 agent。")
            for module, error in errors.items():
                print(f"  {module} 加载失败：{error}")
            return 0
        print(f"共 {len(rows)} 个 agent：\n")
        for row in rows:
            needs = "、".join(row["requires"]) or "无外部依赖"
            print(f"  {row['name']:<18} [{row['kind']}]  {row['description']}")
            print(f"  {'':<18} 依赖：{needs}   产出：{'、'.join(row['produces'])}")
            used = _agent_tools(row["name"])
            if used:
                print(f"  {'':<18} 工具：{'、'.join(used)}")
        for module, error in errors.items():
            print(f"\n注意：{module} 加载失败（{error}），该组 agent 不可用。")
        return 0

    if args.action == "tools":
        from ..agents.tools import tool_catalog

        tools = tool_catalog()
        if not tools:
            print("还没有注册任何工具。")
            return 0
        print(f"共 {len(tools)} 个工具（反爬能力都在工具里）：\n")
        for tool in tools:
            params = "，".join(tool["params"]) or "无参数"
            needs = "、".join(tool["requires"]) or "无外部依赖"
            print(f"  {tool['name']:<20} {tool['description']}")
            print(f"  {'':<20} 参数：{params}   依赖：{needs}")
        return 0

    steps = list(args.names)
    if not steps:
        print("请给出要跑的 agent 名，例如：agents run zhihu --company 茶百道")
        print("可用：" + "，".join(r["name"] for r in catalog()))
        return 2

    request = AgentRequest(
        company_name=args.company or "",
        company_key=args.company_key,
        resume=_read_json(args.resume),
        job=_read_json(args.job),
    )
    if not request.company_name and request.resume is None and request.job is None:
        print("至少给 --company / --resume / --job 之一。")
        return 2

    ctx = _build_agent_context(args)
    try:
        results = asyncio.run(_run_agents_once(steps, request, ctx))
    finally:
        asyncio.run(_close_agent_context(ctx))

    if args.json:
        payload = {"run_id": request.run_id, "results": [r.to_dict() for r in results]}
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    print()
    for result in results:
        _print_agent_result(result)
    bad = [r for r in results if r.status.value in ("blocked", "failed")]
    return 1 if bad and not any(r.usable for r in results) else 0


def _read_json(path: str | None):
    if not path:
        return None
    import json
    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8"))


async def _run_agents_once(steps, request, ctx):
    from ..agents import Pipeline

    return await Pipeline(steps).run(request, ctx)


async def _close_agent_context(ctx) -> None:
    """释放抓取资源。浏览器可能根本没启动，close 里要能容忍 None。"""
    for name in ("browser", "http"):
        resource = getattr(ctx, name, None)
        if resource is None:
            continue
        try:
            await resource.close()
        except Exception:  # noqa: BLE001 - 收尾失败不该盖住主结果
            pass


def _build_agent_context(args):
    """按需装配 HTTP / 浏览器。浏览器惰性打开，不用就不启动 Chromium。"""
    from pathlib import Path

    from ..agents import AgentContext, HttpFetcher, StealthBrowser
    from ..engine import Logger

    http = HttpFetcher(delay=2.0, timeout=25.0, retries=1)
    browser = None
    if not getattr(args, "no_browser", False):
        browser = StealthBrowser(state_file=getattr(args, "state", None))
    return AgentContext(
        logger=Logger("info"),
        http=http,
        browser=browser,
        options={"dump_dir": getattr(args, "dump_dir", None), "cwd": str(Path.cwd()),
                 "no_browser": bool(getattr(args, "no_browser", False))},
    )


def _print_agent_result(result) -> None:
    """把 agent 结果打印成人能读的样子。"""
    icon = {
        "ok": "✓", "partial": "◐", "empty": "○", "blocked": "⊘", "failed": "✗",
    }.get(result.status.value, "?")
    print(f"{icon} {result.agent}  [{result.status.value}]  {result.elapsed_s:.1f}s")

    if result.error:
        print(f"   错误：{result.error}")
    for note in result.notes:
        print(f"   说明：{note}")

    if result.score is not None:
        card = result.score
        print(f"   总分 {card.total}  等级 {card.grade}  {card.verdict}")
        for dim in card.dimensions:
            print(f"     - {dim.name:<10} {dim.score:>5.1f}  权重 {dim.weight}")
            if dim.reason:
                print(f"       {dim.reason}")
        if card.advice:
            print("   提升方向：")
            for item in card.advice:
                print(f"     · {item}")

    if result.findings:
        print(f"   证据 {len(result.findings)} 条：")
        for finding in result.findings[:8]:
            senti = "" if finding.sentiment is None else f" [{finding.sentiment:+.0f}]"
            print(f"     - <{finding.source}>{senti} {finding.title[:60]}")
            if finding.url:
                print(f"       {finding.url}")
        if len(result.findings) > 8:
            print(f"     ... 其余 {len(result.findings) - 8} 条（加 --json 看全部）")
    print()
