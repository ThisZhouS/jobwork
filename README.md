# BOSS直聘 职位信息爬虫（scrapling）

用 [scrapling](https://github.com/D4Vinci/Scrapling) 0.4.8 的 `StealthySession`（底层 patchright）抓取
BOSS直聘 的职位列表与职位详情，重点解决两类反爬措施：

* **控制台检测**：站点周期性 `console.table` / `console.clear` 打印大对象，用耗时差判断
  DevTools / CDP 是否连上；
* **会话页面销毁**：被判定为自动化后，页面会 `window.close()` 或跳 `about:blank`，
  DOM 被清空，抓取中断。

登录态、职位数据都落在本地，不上传任何地方。

---

## 1. 项目结构

按「命令行 → 采集 / 结构化 / 存储」分层，依赖只允许向下；跨子包调用只走门面
（`boss_crawler.crawl` / `boss_crawler.structuring` / `boss_crawler.store`）。
每个目录的详细索引见 `Tree/Tree.md`。

```
boss_crawler/
  __init__.py        包门面（稳定公共 API）
  config.py          城市编码、接口地址、节流参数、薪资/经验/学历档位码、Ark/PG 配置
  filters.py         筛选参数解析：界面文案 <-> 接口数字码（叶子，无内部依赖）
  industry_codes.py  96 个行业码
  stealth.js         反检测脚本（console 探测中和 + 页面自毁拦截 + 心跳），运行时由 browser.py 注入
  structuring/       结构化层：纯函数、无 IO，可离线单测
    jd.py              JD 结构化编排：structure_jd()
    jd_sections.py     分节与切条目（SECTION_NAMES / split_sections / 横幅与噪声过滤）
    jd_extract.py      标量抽取（年限/学历/招聘人数/工时/福利/资深度）
    jd_skills.py       技能词表、抽取、规范化与分类
    text.py            文本与地址：公司名规范化、地址拆解、薪资单位
    cleaning.py        记录级清洗：clean_record / 公司聚合 / 质量报告
  crawl/             采集层
    browser.py         BossBrowser：持久化登录态、反检测注入、页面健康检查/重建
    parser.py          JSON/DOM 解析（含工资解析、详情字段容错）
    job_crawler.py     JobCrawler：SPA 预热 -> 列表分页 -> 详情补全 -> 风控恢复
  store/             持久化层
    jsonl.py           JSONL 主存 + CSV 导出（按 job_id upsert 去重）
    dataset.py         输入展开与记录合并（enrich/process/db-load/embed 共用）
    schema.py          建表 DDL 与列定义（表结构唯一事实来源）
    postgres.py        Database：连接、写入、向量检索、统计
  embedding.py       火山方舟向量化客户端（批量、重试、内容指纹幂等）
  export.py          导出 Excel（岗位明细 / 公司汇总 / 数据质量）
  cli/               命令行层
    parser.py          参数定义 + 共享参数组（add_input_args / add_db_args）
    commands.py        每个子命令一个 cmd_*，只做编排
    __init__.py        main()：异常归一 + 按 args.func 派发
tests/               102 条单元测试（按包结构对应）
scripts/
  research/          早期接口探测与反爬取证（一次性留档，不属于生产路径）
  anti_detect_check.py 反检测自检
Tree/                目录索引（Tree.md + 各目录说明）
db/schema.sql        库结构快照（pg_dump --schema-only）
pyproject.toml       依赖与入口点 boss-crawler
output/              抓取结果
output/clean/        清洗结果（jobs.xlsx / companies.csv / jobs_clean.*）
.state/              登录态 profile 与密钥（敏感，勿提交）
```

---

## 2. 快速开始

```powershell
pip install -r requirements.txt          # scrapling + patchright + browserforge
python -m patchright install chromium    # 首次需要下载 patchright 的浏览器

python -m boss_crawler login             # 弹出窗口，用 BOSS直聘 App 扫码
python -m boss_crawler doctor            # 自检：浏览器 / 登录态 / 接口
python -m boss_crawler filters           # 查看筛选参数可选值
python -m boss_crawler crawl -q Python -c 成都 -p 2 --detail
python -m boss_crawler process           # 结构化 + 清洗，输出公司/地址清单
python -m boss_crawler enrich            # 回源补全 JD/地址，可断点续跑
python -m boss_crawler db-init           # 建库表（含向量列与相似度函数）
python -m boss_crawler db-load           # 元数据入库
python -m boss_crawler embed             # 向量化并写回同一行
```

带筛选的抓取（岗位、城市、薪资、学历、工作经验、公司行业都可作为参数）：

```powershell
python -m boss_crawler crawl -q Python -c 成都 -p 2 `
  --salary 20-50K --experience 3-5年 --degree 本科 --industry 计算机软件 `
  --detail
```

输出：

* `output/jobs_Python_成都_<时间戳>.jsonl`：一行一个职位，含详情字段；
* `output/jobs_Python_成都_<时间戳>.csv`：Excel 可直接打开（UTF-8 BOM）。

常用参数：

| 参数 | 说明 |
| --- | --- |
| `-q/--query` | 搜索关键词（岗位） |
| `-c/--city` | 城市名（见 `config.CITY_CODES`）或 city code |
| `-p/--pages` | 抓取页数，每页 30 条 |
| `--salary` | 薪资档位：`3K以下`/`3-5K`/`5-10K`/`10-20K`/`20-50K`/`50K以上` |
| `--experience` | 经验：`在校生`/`应届生`/`经验不限`/`1年以内`/`1-3年`/`3-5年`/`5-10年`/`10年以上` |
| `--degree` | 学历：`初中及以下`/`中专/中技`/`高中`/`大专`/`本科`/`硕士`/`博士` |
| `--industry` | 公司行业：`互联网`/`计算机软件`/`人工智能`/`电子商务`… 共 96 个，见 `python -m boss_crawler filters` |
| `--take` | 最多保留条数（调试用） |
| `--detail` | 同时抓职位详情（描述、地址、公司介绍） |
| `--headless` | 无头模式；**更易被检测，不推荐** |
| `--out` | 输出目录 |

筛选参数既支持界面文案，也支持接口数字码（`--salary 406`、`--industry 100021`），
数字码会原样透传，方便使用界面上没列出的档位。

---

## 3. 筛选参数是怎么接上的

职位页的筛选项最终会变成列表接口的查询参数。实测（`scripts/research/filter_params.py`）：

* 页面上的筛选状态回写到 URL：`/web/geek/jobs?query=Python&city=101270100&salary=406&experience=105&degree=203`；
* 前端真正请求列表时用的是 **POST**，表单体同样带这些字段：
  `page=1&pageSize=15&city=…&salary=406&experience=105&degree=203&query=Python&industry=&scale=&stage=…`；
* 直接对 `joblist.json` 用 **GET + 同样的参数**，返回 `code=0` 且结果确实被过滤（薪资/经验/学历/行业逐项验证过）。

因此爬虫不需要去点页面上的下拉框，只要把参数拼到接口和预热页 URL 上即可，
既稳定又不会因为点选动作触发额外风控。

编码来源：

| 筛选项 | 接口参数 | 取值 |
| --- | --- | --- |
| 薪资待遇 | `salary` | `402`~`407` |
| 工作经验 | `experience` | `101`~`108` |
| 学历要求 | `degree` | `202`~`209` |
| 公司行业 | `industry` | 数字行业码，如 `100020` 互联网、`100021` 计算机软件 |
| 城市 | `city` | 城市码，如 `101270100` 成都 |

薪资/经验/学历的码值来自页面上的 `ka="sel-job-rec-salary-406"` 这类属性；
行业的码值没有直接暴露在 DOM 里，是用 `scripts/research/collect_industry_codes.py`
从真实职位数据的 `brandIndustry ↔ industry` 字段反推采集的（96 个），
生成到 `boss_crawler/industry_codes.py`。父级行业码会自动包含子行业。

> 注意：薪资是平台的**档位**，按区间重叠匹配——筛 `20-50K` 时 `15-30K` 也会出现
> （因为两段有交集）。需要严格区间时，请对结果里的 `salary_min` / `salary_max` 再过滤。
> 城市写「全国」即 `city=100010000`。

---

## 4. 补全与结构化（enrich + process）

原始记录有两类硬伤：**只有抓过详情的记录才有完整地址和 JD 正文**（列表接口只给
城市/区/商圈和摘要），以及**公司名被平台脱敏或截断**。所以分两步：

```powershell
python -m boss_crawler enrich             # ① 回源补详情（JD/地址/技能/福利），逐条落盘可断点续跑
python -m boss_crawler process            # ② 清洗 + JD 结构化，纯本地不联网
python -m boss_crawler process -i output/jobs_Python_成都_*.jsonl -o output/clean
```

### 4.1 补详情（enrich）

`enrich` 只对「缺 JD 或 缺详情地址」的记录发请求，每补完一条就写入
`output/clean/enriched.jsonl`，中断后重跑会自动跳过已完成的，不会重复请求。

本次实测把 JD 覆盖率从 **13/54 拉到 53/54**、详情地址从 **12 条到 52 条**。
唯一没补到的是「建筑运维数据分析师」——详情接口返回 `code=200301 该职位已不存在`，
属于**职位已下架**，保留为空，不编造。

### 4.2 JD 结构化（`structuring/jd*.py`）

BOSS 的 JD 是一整段纯文本，`structuring/jd_sections.py` + `jd_extract.py` + `jd_skills.py` 用规则把它拆成可查询的结构（不调模型、结果可解释）：

**① 分节**——两类标题都能识别：
* 固定词表：`岗位职责`/`工作内容`/`任职要求`/`任职资格`/`技能要求`/`加分项`/`福利待遇`/`公司介绍`/`工作地点`/`工作时间`；
* 中文序号标题：`一、岗位职责`、`二、能力要求`（词表里没有的标题按关键词自动归类，
  如「能力要求」→ 要求、「薪资待遇」→ 福利）；
* 第一个标题**之前**的正文通常是职责（很多 JD 直接以「1、负责…」开头，标题在后面），
  会被归入职责而不是丢掉；非职责的开场白（如「工作周期:长期兼职」）落到 `other` 保留。

**② 切条目**——支持 `1、`/`1.`/`①`/`•`/`-`、换行，以及完全没有编号时用 `；` 分隔；
`3.5年`、`2024.10` 这类数字不会被误切。

**③ 抽字段**（抽不到就留空，不猜）：

| 字段 | 抽取方式 | 实测覆盖 |
| --- | --- | --- |
| `responsibilities` | 职责区块 + 标题前正文 | 49/54（均 3.7 条） |
| `requirements` | 要求区块 | 46/54（均 4.2 条） |
| `skills` | 技能词典命中 + 平台技能串规范化 | 53/54，95 个实体 |
| `benefits` | 福利词典 + 平台福利标签 | 54 个实体 |
| `min_years`/`max_years` | `3-5年` / `5年以上` / `经验不限` | 19/54 |
| `degree_required` | JD 里的学历词，缺失则回落平台字段 | 54/54 |
| `work_schedule` | 双休/大小周/单休/996/弹性/排班 | 13/54 |
| `seniority` | 岗位名里的 实习/应届/高级/资深/专家/经理/总监 | 9/54 |
| `hiring_count` | `招N人` | 0/54（源数据里根本没有该信息） |

**技能规范化**：平台返回的 `skills` 常是描述串，直接当实体入库会脏：

```
"Linux开发/部署经验"      -> Linux
"Spark原理/源码"          -> Spark
"经济/工商管理相关专业"    -> （丢弃，不是技能）
"langChain、langGraph"    -> langChain, langGraph
"互联网/科技"             -> （丢弃）
```

职责/要求这类**段落内容**是逐条数组（不是一坨文本），技能/福利是**独立实体**，
所以可以按「会 Python 且要求双休」这种条件直接 join 查询。

### 4.3 产物（默认 `output/clean/`）

| 文件 | 内容 |
| --- | --- |
| `companies.csv` | **公司清单**：公司名、工商全称、行业、规模、岗位数、地址集合、地址来源（`detail`/`list`）、月薪区间、岗位示例 |
| `jobs.xlsx` | 三个工作表：岗位明细（25 列，含结构化字段）/ 公司汇总 / 数据质量 |
| `jobs_clean.csv` / `jobs_clean.jsonl` | 逐岗位的结构化记录（公司块 + 地址块 + JD 结构化块） |
| `clean_report.json` | 质量统计：地址完整/派生/缺失、脱敏公司数、JD/职责/要求/技能覆盖 |
| `enriched.jsonl` | `enrich` 补到的详情，`process` 自动复用，不会重复请求 |

### 4.4 清洗规则

**公司名**（`company` 块）

| 字段 | 说明 |
| --- | --- |
| `name` | 规范化后的公司名（全角转半角、压缩空白、去掉首尾标点与 `...`） |
| `legal_name` | 从公司介绍首句提取的工商全称，如「华为技术有限公司」 |
| `is_anonymous` | 平台脱敏岗位（「某大型互联网公司」「某知名智能硬件公司」） |
| `is_truncated` | 列表接口把公司名截断（「成都悠鑫龙商务信...」） |
| `raw` | 清洗前的原值，便于回溯 |

> `legal_name` 来自公司介绍，对脱敏岗位可能是**用人方/客户**（例如介绍是华为），
> 不一定是签约主体——所以要配合 `is_anonymous` 一起看，不做推断。

**地址**（`workplace` 块）

| 字段 | 说明 |
| --- | --- |
| `full` | 完整地址（优先用详情接口原文） |
| `city` / `district` | 城市、区县（详情地址里解析出的区县优先于列表字段） |
| `business_district` | 商圈 |
| `detail` | 去掉城市与区县后的详细地址（楼宇、门牌、楼层） |
| `source` | `detail`（详情接口）/ `list`（城市+区+商圈派生）/ `city-only` / `none` |

* 详情地址只给了「成都」这种城市级信息时，退化为「城市+区+商圈」的派生地址，
  并把 `source` 标成 `list`，**不会假装是完整地址**；
* 站点会把「商圈+详细地址」拼在一起造成整段重复，`collapse_repeat_prefix` 折叠成一段；
* 日薪/时薪（`100-200元/天`）单独标 `salary_unit`，不参与公司月薪区间聚合；
* 所有「读不到」的字段留空，不做推测填充。

### 4.5 本次数据实测（54 条职位）

```
地址：完整 52 条，派生于城市/商圈 2 条，缺失 0 条
公司：脱敏 6 家，截断 1 家，补全工商全称 16 家
JD ：53/54 条有正文，职责 49 条（均 3.7）、要求 46 条（均 4.2）
技能：95 个实体 / 339 条岗位关联；福利：54 个实体
```

剩下 1 条没有 JD 的是职位已下架（`200301`），4 条没有「职责」是因为 JD 只写了
技能要求与岗位需求、没有职责段落——都是**源数据没有**，不是解析失败。

---

## 5. PostgreSQL 存储与向量化

元数据与向量**存在同一个库里、同一行上**：`jobs` / `companies` 两张表各自带
`embedding`、`embedding_model`、`embedding_dim`、`embedding_hash`、`embed_text`、
`embedded_at`，所以拿到元数据就同时拿到了向量，不需要额外 join。

```powershell
python -m boss_crawler db-init            # 建表 + 建余弦相似度函数 + 建视图
python -m boss_crawler db-load            # 清洗后的元数据入库（含原始 JSON）
python -m boss_crawler embed              # 调 doubao-embedding-vision 向量化并写回
python -m boss_crawler search -q "大模型算法工程师" -k 5
python -m boss_crawler db-stats           # 库内存量与向量化状态
```

### 本机环境（实测）

| 项 | 值 |
| --- | --- |
| PostgreSQL | 18.1（Windows，`D:\postgresSQL`，127.0.0.1:5432） |
| 数据库 / 用户 | `boss_jobs` / `postgres`（密码放 `.state/pg_password.txt`，可用 `PGPASSWORD` 覆盖） |
| pgvector | **未安装**（机器没有 Windows SDK，`corecrt.h` 缺失，无法编译扩展；PG18 也没有官方 Windows 预编译包） |
| 相似度实现 | `real[]` 存向量 + PL/pgSQL 函数 `cosine_similarity(real[], real[])` |

> 如果之后装上了 pgvector（`CREATE EXTENSION vector;`），`db-init` 会自动加
> `embedding_vec vector(N)` 列与 HNSW 索引，`search` 改用 `<=>` 算子；
> 这条分支在本机**没有实测**，代码里是检测到扩展才走。

### 火山方舟（Ark）向量化接口实测

| 项 | 结论 |
| --- | --- |
| 可用端点 | `https://ark.cn-beijing.volces.com/api/plan/v3`（**官方 `/api/v3` 对本账号返回 401**） |
| 接口 | `POST {base}/embeddings`，body `{"model": ..., "input": ["文本", ...]}` |
| 图文接口 | `POST {base}/embeddings/multimodal`，`input: [{"type":"text","text":...}]` |
| 模型 | `doubao-embedding-vision-250328`（响应里回显实际模型 `doubao-embedding-vision-251215`） |
| 维度 | **2048** |
| 批量 | 支持，一次多条 `input` 按 `index` 对应返回 |
| 密钥 | `.state/ark_key.txt` 或环境变量 `ARK_API_KEY`，不入库、不打印 |

被向量化的「必要数据」：

* **岗位**：岗位名 + 公司名 + 行业 + 城市/区/商圈 + 地址 + 薪资 + 经验 + 学历 +
  **结构化技能/福利 + 职责前 6 条 + 要求前 6 条** + JD 原文（截半）；
* **公司**：公司名 + 工商全称 + 行业 + 规模 + 融资阶段 + 城市 + 地址 + 公司介绍。

两者都按 `EMBED_MAX_CHARS`（默认 1500 字）截断，避免超长 JD 撑爆 token。
用结构化后的职责/要求喂向量，比只喂原始 JD 更聚焦——实测把「数据仓库 ETL 数据治理」
的检索结果从泛泛的 Python 岗收敛到数据开发/AI 中心岗。

### 结构化表结构（不只是把文本塞进一个字段）

`jobs` 表除元数据外，还带 JD 结构化列；技能与福利是**独立实体 + 关联表**，
所以能直接做「会 Python 且双休」这类 join 查询：

| 对象 | 内容 |
| --- | --- |
| `jobs.responsibilities` / `jobs.requirements` | 职责、要求（`text[]`，逐条数组） |
| `jobs.jd_sections` | 全部区块（职责/要求/加分项/福利/公司/地点/工时/其他）`jsonb` |
| `jobs.jd_skills` / `jobs.jd_benefits` | 结构化技能、福利（`text[]`） |
| `jobs.min_years` / `max_years` / `degree_required` / `hiring_count` / `work_schedule` / `seniority` / `has_jd` / `jd_length` | 量化字段 |
| `skills(name, category)` | 技能实体 + 分类（数据/算法AI/后端/前端/测试运维/产品业务/通用） |
| `job_skills(job_id, skill, source)` | 岗位-技能关联（本次 339 条） |
| `benefits(name)` / `job_benefits(job_id, benefit)` | 福利实体与关联（本次 466 条） |

实测：`skills` 103 个实体（数据 29、后端 24、算法/AI 14…），`job_skills` 347 条关联，
`benefits` 55 个，`job_benefits` 466 条。查询示例：

```sql
-- 既要 Python 又要双休的岗位
SELECT j.title, j.company_name, j.salary
FROM jobs j
JOIN job_skills js ON js.job_id = j.job_id AND js.skill = 'Python'
JOIN job_benefits jb ON jb.job_id = j.job_id AND jb.benefit = '双休';

-- 技能需求排行
SELECT skill, count(*) FROM job_skills GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```

### 幂等与可追溯

* 每行存 `embedding_hash = sha256(被向量化原文)[:32]`；`embed` 只处理
  「没有向量 / 换了模型 / 原文指纹变了」的行。第二次执行实测 **0 条待处理、0 次接口调用**；
* 每次批量写入都会记一条 `embedding_runs`（对象类型、模型、维度、条数、时间），便于追溯；
* `db-load` 的列清单**故意不含向量列**，所以重复导入元数据不会把已有向量清空。

### 检索示例

```powershell
python -m boss_crawler search -q "大模型算法工程师" -k 4
```

```
1. [0.5522] Python全栈工程师(AI方向) @ 郑州某大型高校信息化服务上市公司 | 郑州中原区 | 20-21K
2. [0.4817] Python智能体开发-双休 @ 美云 | 成都武侯区 | 11-13K
3. [0.4722] 搜索推荐算法 @ 本手信息 | 成都双流区 | 20-40K
4. [0.4540] 1.2w-3w/月python开发工程师/五险一金 @ 意聪科技 | 成都郫都区 | 15-30K
```

返回的每一行都带公司名与地址——这正是做公司背调时需要的元数据。

---

## 5.5 公司背调（`dd` 子命令）

把库里只有公司名的 48 家（6 家脱敏的跳过），补成有工商档案、母子公司关系、
风险记录的实体，全部写回 PostgreSQL。

### 两条取数路线：先免费，再考虑付费

| 路线 | 成本 | 怎么用 | 拿得到什么 |
|---|---|---|---|
| **天眼AI（CLI）** | **免费** | `tyc login` 后 `dd --source cli` | 核心工商、风险总览、简介、规模、标签、知产评分、招投标 |
| 开放平台（REST） | ¥1/家 起，**充值门槛 100/1000** | `.env` 填 token，`dd --source api` | 上面全部 + 完整股权树、分支机构、失信/被执行明细 |

**结论：求职背调走免费路线就够。** 判断「这家公司靠不靠谱」需要的是登记状态、
风险总览的数量与类型、规模、简介；完整股权树是加分项，不是必需项。

天眼AI 的实际免费额度（读 `tyc <类别>` 输出里的「数据权益」字段确认，2026-10）：

| 免费可用 | 需要 VIP（宽限期已于 2026-09-01 结束） |
|---|---|
| `company companies`（实体锚定） | `company external-investments`（对外投资） |
| `company registration-info` | `company equity-tree`（股权穿透） |
| `company profile` / `scale` / `tags` / `logo` | `company controlled-companies`（控制企业） |
| `company accuracy` | `company branches`（分支机构） |
| `risk overview`（**背调最有用**） | `company annual-reports` / `contact-info` / `change-records` |
| `operation bids` | `history historical-overview` |
| `intellectual_property ipr-score` | `executive person-profile` |

### 凭据

```powershell
# 路线一（免费）：装 CLI + OAuth 登录，不需要买任何接口
npm install -g tyc-cli
tyc login          # 浏览器授权，Device Flow 会给 6 位验证码

# 路线二（付费，可选）：把 token 写进 .env
Copy-Item .env.example .env
# 编辑 .env，填 TIANYANCHA_TOKEN=...
```

token 只从 `.env` 或 `.state/tyc_token.txt` 读；缺 token 时命令退出码 3，
不会静默跳过。`.env` 已在 `.gitignore` 里。

### 用法

```powershell
# 先看要花多少钱（不调接口）
python -m boss_crawler dd --dry-run

# 免费路线（推荐）
python -m boss_crawler dd --source cli --limit 5

# 付费路线：每家 ¥1.31，每查一家关联方风险再 ¥0.30
python -m boss_crawler dd --source api --max-related 3 --max-cost 100

# 只抓工商与母子公司关系，完全不查失信/被执行
python -m boss_crawler dd --skip-risks

# 预算紧：不查关联方风险，只背调主体本身
python -m boss_crawler dd --depth 0
```

### 接口与真实单价（页面标价，2026-10）

| 接口 | 用途 | 单价 |
|---|---|---|
| 816 搜索 | 名称 → 天眼查实体 | ¥0.01 |
| 1001 工商全景 | 档案 + 母子/分支 + 经营异常/严重违法/行政处罚 | ¥1.00 |
| 843 失信人 | 自身与关联方 | ¥0.15 |
| 839 被执行人 | 自身与关联方 | ¥0.15 |

`fprice` 单位是**分**，不是元——这一点容易看错 100 倍。

### 母公司与子公司怎么取

`1001` 一次返回三个方向，不用额外花钱：

| 字段 | 关系 | 说明 |
|---|---|---|
| `headquarters` | 母公司 | 工商登记的总公司 |
| `investList` | 子公司 | 按 `percent` 分级：100% 全资、>50% 控股、≥20% 参股 |
| `branchList` | 分支机构 | 分公司，非法人，不当子公司算 |

低于 `--min-percent`（默认 20%）的对外投资视为财务投资，不入库——
避免把 5% 的理财式持股当成关联方。

### 落库

```sql
-- 一家一行：关系数 + 自身/母公司/子公司风险数
SELECT company_name, legal_person, reg_status, staff_num,
       parent_cnt, subs_cnt, self_risks, parent_risks, subs_risks
FROM tyc_dd_overview ORDER BY (self_risks + parent_risks + subs_risks) DESC;

-- 母子公司有雷的，会通过 related_key 汇聚到主体名下
SELECT c.company_name, r.relation, k.risk_type, k.department, k.reason
FROM tyc_risk k
JOIN companies c ON c.company_key = k.related_key
JOIN tyc_relation r ON r.from_key = k.related_key AND r.to_name = k.entity_name
ORDER BY c.company_name, r.relation;
```

四张表 `tyc_company` / `tyc_relation` / `tyc_risk` / `tyc_fetch_log`，
加一个汇总视图 `tyc_dd_overview`。重跑幂等（先删后插 + upsert）。

### 设计要点

- **名称匹配单独打分**：BOSS 上多是简称（`茶百道` → `四川茶百道实业股份有限公司`），
  互相包含给 0.75~1.0，低于 0.85 会标「需人工确认」而不是静默采信；
  优先用 `legal_name`（工商全称）去查。
- **免费的风险不重复买**：经营异常/严重违法/行政处罚已在 1001 里，
  只有失信、被执行人需要单买。
- **预算硬上限**：`--max-cost` 到了就停。
- **调用留痕**：每次请求都写 `tyc_fetch_log`（接口、错误码、耗时、价格），
  跑完可以直接对账。
- **鉴权错误不重试**：`300009`（账号信息有误）、`300003`（余额不足）直接失败
  并提示去检查 token / 充值，重试只会白烧请求。

详见 `Tree/providers.md`。

---

## 5.6 异步引擎（`engine/`，对标 Scrapy）

背调这类「几百个请求、彼此独立、偶尔失败」的活，顺序跑太慢、手写并发又容易漏掉
重试与收尾。所以抽了一层通用内核，天眼查作为第一个接入的 spider。

| Scrapy | 这里 | 差异 |
|---|---|---|
| Engine | `engine/engine.py` | 收尾条件显式化 |
| Scheduler + dupefilter | `engine/scheduler.py` | `asyncio.PriorityQueue` + 指纹去重 |
| Downloader / AutoThrottle | `engine/downloader.py` | 按主机限速、自适应间隔 |
| Downloader Middleware | `engine/middleware.py` | 三个钩子 |
| Spider | `engine/spider.py` | 回调按 `Request.callback` 分发 |
| Item Pipeline | `engine/pipelines.py` | `item_type` 代替多个 Item 类 |
| Signals | `engine/signals.py` | 支持异步回调 |
| RetryMiddleware | `engine/retry.py` | **HTTP 码 + body 业务码** |

### 用法

```powershell
# 默认走引擎：并发 4、同主机 0.35s、最多重试 3 次
python -m boss_crawler dd --concurrency 6 --max-cost 100

# 逐家顺序跑（便于逐步调试）
python -m boss_crawler dd --engine sync
```

### 三个关键设计

**收尾条件要四个都满足**：生产者结束 + 队列空 + 无在飞 + 无待重试。少一个都会
把「链路刚产出新请求」误判成结束。

**重试只在一处退避**。传输层只把异常转成 `Response.error`，不重试；退避统一由
引擎的 `RetryPolicy` 做（指数 + 抖动）。两处都退避的话，实际等待会变成两层叠加。
业务码也在这里判——天眼查 HTTP 200 却在 body 里报错，只看状态码会把「限流」当成功。
`spider.should_retry` 可以覆盖，但引擎**始终强制次数上限**，防止业务侧写错导致死循环。

**失败必须可见**。重试用尽时发 `request_gave_up` 信号，`dd` 会把失败的公司、
接口、错误码列出来。否则调用方只看到「请求数变少了」，说不清哪家、为什么。

### 为什么保序又并发

`psycopg2` 的连接不是线程安全的，所以落库管道用 `ThreadPoolExecutor(max_workers=1)`
把阻塞调用挪出事件循环，同时保证同一连接始终只被一个线程使用。风险行按公司缓冲、
收尾时一次性替换（`replace_tyc_risks` 是先删后插，逐条写会互相删掉）。

### 扩展方式（都不用改引擎）

- **加数据源**：写一个 `Spider` 子类，`start_requests` + 若干 `parse_*`；
- **加产物**：定义新 `item_type`，写一个 `ItemPipeline`，注册进 `pipelines=`；
- **加横切逻辑**（签名、代理、埋点）：写一个 `DownloaderMiddleware`。

详见 `Tree/engine.md`。

---

## 5.7 工具层 + 可组合 agent（`agents/`）

背调与评分不再是写死的流水线，而是分成两层：

```
agent（薄）  ──调用──▶  工具（厚：含全部反爬）
只负责汇总              UA 轮换 / 节流 / 重试 / cookie 登录态 /
                       浏览器兜底 / 被挡识别 / 解析 / 原始页落盘
```

**为什么这样分**：反爬是"怎么拿到"，总结是"拿到后怎么解读"，两者生命周期完全不同。
反爬要频繁调整（站点一改就变），总结口径相对稳定。分开之后，站点改版只改一个工具，
八个 agent 一行不动。

```powershell
python -m boss_crawler agents tools     # 9 个工具及依赖
python -m boss_crawler agents list      # 8 个 agent，含各自调用的工具
```

| 工具 | 做什么 |
| --- | --- |
| `zhihu_search` | 知乎搜索（JSON 接口优先，HTML 兜底） |
| `tieba_search` | 贴吧同名吧 + 全站搜索 |
| `weibo_search` | 微博移动端 container 接口 |
| `tianyancha_search` / `_company` / `_risk` / `_full` | 天眼查网页端：锚定主体、工商档案、风险子页、一站式 |
| `tyc_bundle` / `tyc_ask` | 天眼AI（tyc CLI）**免费工具白名单** |

| agent | 调用的工具 | 状态 |
| --- | --- | --- |
| `zhihu` | `zhihu_search` | 可用（需登录态） |
| `tieba` | `tieba_search` | 可用（多数免登录） |
| `weibo` | `weibo_search` | 可用（移动端接口常免登录） |
| `tianyancha_web` | `tianyancha_full` | 可用（免登录，有限频） |
| `tianyan_ai` | `tyc_bundle` | 可用（需 `tyc login`） |
| `company_score` / `resume_score` / `job_fit` | —— | **空框架，规则待定义** |

```powershell
python -m boss_crawler agents run tianyan_ai --company 茶百道
python -m boss_crawler agents run tianyancha_web tianyan_ai company_score --company 茶百道
```

### 评分 agent 目前是空框架

三个评分 agent 已声明好维度与权重，但**不含任何评分规则**——分值怎么算属于业务判断，
留给你定义。填法：给 `Rule.scorer` 一个函数，返回 0–100，或返回 `None` 表示"没数据"：

```python
def score_status(ctx):                       # ctx: ScoreContext
    status = ctx.profile.get("reg_status")
    if not status:
        return None
    return 90 if ("存续" in status or "在业" in status) else 20

Rule("经营稳定性", weight=3.0, hint="登记状态", scorer=score_status)
```

规则未定义时 agent 返回 `PARTIAL`、给中性分 60、并在 `notes` 里写明
"规则未定义：…"，不会伪装成算完了。`ScoreContext` 提供
`profile / counts / findings / metrics / resume / job`；`scoring/rubric.py`
里有写规则常用的纯函数（区间插值、覆盖率、年限解析、缺口话术）。

### 加/删模块

- 加一个站点 = 新建 `tools/sites/x.py` + `register_tool`，再在 `sites/__init__.py` 加一行；
- 加一个 agent = 新建文件 + 声明 `tools = (ToolCall("x_search"),)`；
- 删一个 = 删文件。`registry` 用 `importlib` 容错加载，删掉整个子包也不会让包导入失败。

详见 `Tree/agent-layer.md`。

---

## 5.8 应用流水线（`app`）：一条命令跑完采集→背调→打分→适配度

把组合方案落成可配置流水线，每步产出都入库，前端只读库：

```
招聘爬虫(BOSS,可插拔) → jobs
   → 背调(天眼查/知乎/微博/贴吧,各自可选) → backduty_evidence / backduty_raw
   → 公司打分(风险/待遇/压力/环境/福利) → company_score
   → 岗位适配度(岗位×简历) → job_fit
   → 定向简历(用户确认后) → resume_version
```

```powershell
python -m boss_crawler app init                 # 建应用层表（幂等）
python -m boss_crawler app status --json        # 自检：库/登录/数据源/agent
python -m boss_crawler app login --platforms zhihu,weibo   # 弹有头浏览器手动登录
python -m boss_crawler app run   --query Python --city 成都 --limit 5 --json
python -m boss_crawler app data  --json         # 前端展示数据
python -m boss_crawler app resume --json        # 简历版本 + 要问用户的问题
python -m boss_crawler app cloud  --json        # 技能词云（按岗位数统计）
python -m boss_crawler app company --company-key K --json   # 公司详情（含劳务派遣）
python -m boss_crawler app job    --job-id J --json         # 岗位详情（含来源链接）
python -m boss_crawler app series --company-key K --field 风险 --json  # 字段折线
python -m boss_crawler app filters --json       # BOSS 筛选条件映射
python -m boss_crawler app models --json        # 模型规格与可用性
```

**可选性**：`--platforms` 选平台；`--no-crawl / --no-backduty / --no-score / --no-fit`
关掉任意一段；`--with-resume` 才生成定向简历。天眼查按方案"不总结、直接存原数据"
（`produces="raw"` → `backduty_raw`）。

**登录**：弹出有头浏览器让人自己登，程序只负责等和记。判定靠关键 cookie
（知乎 `z_c0`、微博 `SUB`、贴吧 `BDUSS`、天眼查 `TYCID`、BOSS `bst`），
登录态存持久化 profile `.state/login/<platform>`，下次复用。**不做自动登录**。

**报错日志**：每个 agent 强制挂 `log_event` 工具，状态非 `OK` 时自动写
`agent_error`（含缺失数据/失败原因），写库失败降级到 `.state/logs/agents.jsonl`。

**其他招聘平台**：`app/sources.py` 的 `JobSource` 是插槽，拉勾/智联/前程无忧已占位，
实现 `build_steps(filters)` 即可接入。

详见 `Tree/app-pipeline.md`（含前端 CLI 契约）。

---

## 5.9 agent 配置（`config/agents.json`）：关掉、换模型、传选项

agent 注册在代码里，但**可调项放在配置里**，改完立即生效，不用重启也不用改代码。

```powershell
python -m boss_crawler app agents                        # 看当前状态
python -m boss_crawler app agent-set --name zhihu --disable
python -m boss_crawler app agent-set --name resume_tailor --model chat=chat.doubao
python -m boss_crawler app agent-set --name job_fit --option max_items=30
python -m boss_crawler app agent-reset --name zhihu      # 恢复默认
```

配置文件长这样（`config/agents.json`）：

```json
{
  "agents": {
    "zhihu":         { "enabled": false },
    "resume_tailor": { "model": { "chat": "chat.doubao" } },
    "job_fit":       { "options": { "max_items": 30 } }
  }
}
```

几个约定：

- `enabled=false` 的 agent 在流水线里**直接跳过**，并写一条 `skipped` 事件，不是静默消失；
- `model` 按**能力**覆盖（`chat`/`embedding`），只影响这一个 agent，不污染其他；
- 写错会**报错而不是忽略**——未注册的 agent、不存在的模型规格一律拒绝。
  这道校验是有意为之：配置写错的代价是"以为生效了其实没有"，比报错更难查。

模型配置同理（`config/models.json`）：

```powershell
python -m boss_crawler app model-set --spec chat.doubao --disable
python -m boss_crawler app model-set --spec embedding.doubao --dimension 1024
python -m boss_crawler app model-reset --spec embedding.doubao
```

桌面端把两者合成一个「配置中心」页签（内部两个子页签：agent / 模型），
勾选框和模型 id 输入框都直接写回配置，写完立即生效。

## 5.10 密钥与安全检查

**仓库里不放任何密钥**，这条由工具守住：

```powershell
python tools/check_secrets.py            # 扫 git 跟踪的文件
python tools/check_secrets.py --all      # 扫工作区（含未跟踪）
```

扫描的形状包括 Ark key、AWS AK、GitHub token、`sk-`、明文 Bearer、
带密码的连接串、以及 `PGPASSWORD=` / `ARK_API_KEY=` / `TIANYANCHA_TOKEN=` 的**字面量赋值**
（`os.environ[...]` 这类表达式不算）。命中只打印头尾，不会把密钥本身写进日志。

`tests/test_secrets.py` 会同时跑「跟踪文件」和「工作区」两遍，所以误提交会被 pytest 拦住。
另外 `.gitignore` 兜住了 `.state/`、`.env*`、`*.pem`、`*.key`、`storage_state.json`、
`config/*.local.json` 等。

**密钥只从两处读**：环境变量，或 `.state/` 下的文件（该目录已被忽略）。
命令行不接受 `--key` 参数——命令行会进 shell 历史，也会出现在进程列表里。

## 5.11 任务队列与重试（对标 Scrapy）

背调阶段原来是「公司 × 平台」两层串行 for，4 个平台就是 4 倍墙钟时间，
任何一个平台被限流整段就卡住。现在换成队列驱动：

```powershell
python -m boss_crawler app run --concurrency 3 --retries 3 --task-timeout 120
```

| 参数 | 默认 | 对应 Scrapy |
|---|---|---|
| `--concurrency` | 3 | `CONCURRENT_REQUESTS` |
| `--retries` | 3 | `RETRY_TIMES`（含首次） |
| `--task-timeout` | 120 | `DOWNLOAD_TIMEOUT` |

保留了三个特性：**并发上限**、**同名任务去重**（键是 `agent:公司`）、
**指数退避 + 抖动**（`min(base·factor^n, max)·(1±0.25)`，抖动是为了避免被限流后
齐刷刷重试）。重试会作为事件播出来，不会静默变慢：

```
! zhihu: 第 1 次尝试失败，0.4s 后重试：RuntimeError: HTTP 429
* backduty [done] 3 家公司，证据 0 条，并发 3，重试 0 次
```

退出时会带 `summary['queue']`（submitted/succeeded/failed/retried/timed_out），
事后能看出这次到底重试了几次。详见 [Tree/app-queue.md](Tree/app-queue.md)。

刻意不引入 Celery/Redis：单进程本地工具，外部 broker 只会让"跑起来"变复杂。

## 5.12 天眼查「风险提示」的平替：巨潮资讯

天眼查的风险提示要付费接口（100 元起充），企查查反而更贵（单次 0.3 元但
**最低充值 500** 且要企业实名）。调研下来唯一「免费 + 免鉴权 + 结构化」的是
**巨潮资讯**的公告接口：

```powershell
python -m boss_crawler app run --platforms cninfo --limit 3
```

- `POST /new/hisAnnouncement/query`，表单 `searchkey=公司名`，无需 token；
- 标题按关键词判 `立案调查 / 重大诉讼 / 失信被执行 / 经营异常 / 股权风险 /
  业绩预警 / 监管问询 / 高管变动`，其余归其他公告；
- 自动翻页（单页 30 条），毫秒时间戳转日期，去掉 `<em>` 高亮标签。

**边界必须说清**：它只覆盖**上市公司**。查非上市企业返回 `EMPTY` 并注明
「非上市公司的正常结果」——**信息不足不等于安全**，工具不会因此给正面分。
有公告但全是常规公告时返回 `PARTIAL`，并附「这不等于无风险」。

实测：康美药业 30 条里 4 条风险（诉讼/高管变动）、比亚迪 50 条 0 条风险、
非上市公司 `EMPTY`。完整的源对比与合规边界见 [Tree/risk-sources.md](Tree/risk-sources.md)。

## 6. BOSS直聘 反爬机制实测

以下结论来自 `scripts/research/` 里的探测脚本与站点 JS，时间 2026-10。

| 机制 | 实测现象 | 本项目对策 |
| --- | --- | --- |
| 控制台检测 | 普通 Playwright 有头模式打开搜索页后，控制台出现成串 `console.table` + `console.clear`，约 6 秒后页面被销毁 | `stealth.js` 把所有探测用 console 方法替换为空操作，`log/info/warn/error` 超过 3 个参数直接丢弃，让「打印耗时」探针拿不到信号 |
| 会话页面销毁 | 同一场景最终 `url=about:blank`，并出现 `Scripts may close only the windows that were opened by them.`（站点调 `window.close()`） | `window.close` 置空、`Location.assign/replace` 拦截 `about:blank`；外层 `BossBrowser.alive()` 每个请求前检查，页面没了立刻重建并重新预热 |
| 环境风控 | 匿名请求 `/wapi/zpgeek/search/joblist.json` 返回 `{"code":37,"message":"您的环境存在异常."}`，带 `seed`/`name`/`ts` | 退避 8~20 秒后重新打开搜索页（让站点自己重新签发 `__zp_stoken__`）再重试，最多 3 次 |
| 登录墙 | 未登录直接跳 `/web/user/`；只复制 `document.cookie` 里的可见 Cookie 会返回 `code:7 当前登录状态已失效` | 登录态由 httpOnly Cookie（`zp_at` 等）承载，无法复制 → 用固定 `user_data_dir` 让爬虫浏览器自己扫码登录一次 |
| 工资字体混淆 | 列表页工资显示为私用区字符（字体 `kanzhun-mix`），文本抓取得到乱码 | 走 JSON 接口，`salaryDesc` 是明文；DOM 兜底只用于拿不到接口时 |
| 浏览器环境 | 普通 Playwright/Chromium 的 `navigator.webdriver`、CDP 指纹会被识别 | scrapling `StealthySession` 基于 patchright，已处理 CDP/指纹；实测同一路径能正常到达登录页而不是被销毁 |

### 3.1 踩到的坑：`init_script` 在 StealthySession 上不生效

scrapling 的 `StealthySession(init_script=...)` 最终调用 patchright 的 `add_init_script`，
而 patchright 用「路由注入」实现它，实测**不会**在导航时执行：

```python
# patchright 与原生 playwright 的对比（scripts/research/ 里有完整脚本）
patchright  marker: None
playwright marker: 42
```

所以 `stealth.js` 改为由 `BossBrowser.arm()` 在每次 `goto()` 之后用 `page.evaluate()` 注入。
站点的探测是周期性循环的，后置注入依然能覆盖后续探测；`doctor` 会打印 `stealth=v1` 确认注入成功。

---

## 7. 关键设计

### 4.1 持久化登录态，而不是复制 Cookie

BOSS直聘 的登录票据主要在 httpOnly Cookie 里，`document.cookie` 读不到；把可见 Cookie
搬到新浏览器会直接 `code:7`。因此 `login` 用固定 profile 目录（`.state/chrome-profile`）
让爬虫浏览器自己完成扫码，之后每次启动都复用。

### 4.2 接口优先，DOM 兜底

列表：`/wapi/zpgeek/search/joblist.json`，一条记录含薪资、经验、学历、公司、BOSS、`securityId` 等。
详情：`/wapi/zpgeek/job/detail.json?securityId=...`，含 `postDescription`、`address`、`brandComInfo`。
两者都在页面上下文里 `fetch(..., {credentials: 'include'})`，自动带上登录态和 `__zp_stoken__`。

好处：不受工资字体混淆影响；页面即使被抓取中途销毁，已经拿到的 JSON 也不会丢。

### 4.3 恢复而不是硬扛

`JobCrawler._fetch_json()` 是唯一出口，所有异常都在这里收敛：

1. `Execution context was destroyed` / `Target closed` → 重建页面、重新预热、重试；
2. `code 37` → 退避 + 重新预热 + 重试（有次数上限，不会死循环）；
3. `code 7` / 消息含「登录」→ 抛 `LoginRequired`，提示重新 `login`。

### 4.4 低频、拟人

默认每页间隔 4~9 秒，每条详情间隔 2~5 秒，风控退避 8~20 秒；`--headless` 默认关闭。
抓取过程中会有滚动等轻微交互。

---

## 8. 数据字段

`job_id`、`security_id`、`lid`、`title`、`salary`、`salary_min`、`salary_max`、`city`、
`district`、`business_district`、`experience`、`degree`、`labels`、`skills`、`welfare`、
`company`、`industry`、`industry_code`、`stage`、`scale`、`boss_name`、`boss_title`、
`boss_online`、`gps`、`url`、`description`、`address`、`company_intro`、`company_size`、
`company_industry`、`company_stage`、`skills_detail`、`source`。

---

## 9. 自检与测试

```powershell
python -m boss_crawler doctor
python -m pytest -q                        # 447 条
python tools/anti_detect_check.py 20      # 真网观测：页面是否会被销毁
```

* `test_parser.py`：薪资解析、列表归一化、详情字段、DOM 兜底；
* `test_recovery.py`：用假 page 模拟「页面销毁 → 重建重试」「code 37 → 退避重试」
  「code 7 → 抛登录异常」「重试次数有上限」，不触网；
* `test_agents_core.py`（41 条）：契约、注册表、Pipeline、状态判定、抓取工具；
* `test_agents_backduty.py`（56 条）：工具注册表与契约、各站点解析、被挡/壳页识别、agent 汇总；
* `test_queue.py`（17 条）：重试、退避、去重、并发上限、优先级、超时；
* `test_cninfo.py`（22 条）：风险分类、日期解析、翻页、降级、标题清洗；
* `test_agent_settings.py`（16 条）：agent 配置读写、校验、作用域覆盖、流水线跳过；
* `test_secrets.py`（13 条）：密钥扫描器自身 + 仓库无密钥断言；
* `test_models_and_views.py`（43 条）：模型规格/开关/覆盖/降级、劳务派遣三态、前端视图契约；
* `test_app_pipeline.py`（26 条）：数据源注册、登录配置、编排三段与失败兜底；
* `test_agents_scoring.py`（26 条）：评分框架（Rule/Rubric/ScoreContext）、空骨架行为、规则工具函数；

全部离线：测试用合成 HTML/JSON 与假 http/browser/cli，不发真实请求。

---

## 10. 合规说明（重要）

BOSS直聘 的 `robots.txt` 对 `/*?*`（几乎所有带查询参数的动态页，包括职位搜索）
以及 `/job_detail/l*.html` 标注了 `Disallow`。本项目是**面向个人求职**的低频工具：

* 只抓取公开可见的职位信息，不复刻站点内容、不做二次分发或售卖；
* 默认节流较保守，单次抓取建议不超过几页；
* 请使用自己的账号登录，不要多人共用同一 profile；
* 若站点明确拒绝或账号被风控，应停止抓取而不是加大频率。

继续使用即表示你自行承担与站点服务条款相关的责任。

---

## 11. 已知限制

* 风控是动态的：`code 37` 可能在任意请求出现，程序会自动退避重试，但极端情况下仍需人工重登；
* **天眼查网页端有硬限频**：实测同一出口连续请求几次后，搜索页会退化成约 22KB 的
  登录墙外壳（零个 `/company/` 链接）。`tianyancha_web` 会把它判成 `BLOCKED`
  并提示降频或换 `tianyan_ai`，而不是假装"没查到"。稳定路线是 `tyc login` 后用 CLI；
* **天眼AI 免费额度不含关系与风险明细**：`dd --source cli` 只写工商档案与风险
  计数，关系表一行都不碰（避免删掉付费接口此前抓到的数据）；
* 知乎/微博需要登录态才能看到搜索结果，本工具不自动过滑块或设备校验，
  请手动登录后用 `--state` 传 cookie 目录；
* 只覆盖 Web 端求职者视角的搜索/详情接口，未实现沟通、投递等写操作；
* 城市编码表是常见城市，其他城市可把 city code 直接传给 `-c`；
* `--headless` 能跑但更容易触发风控，建议保持有头。



