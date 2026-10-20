# Tree 索引

BOSS直聘 岗位采集 → JD 结构化 → PostgreSQL（元数据与向量同行）的最小工程结构。
每个目录一个 `Tree/<目录名>.md`，说明文件、主要类/函数与扩展位置。

```
<仓库根目录>\
├── boss_crawler/            生产代码（单包、分层，依赖只允许向下）
│   ├── cli/                 命令行：参数解析 + 子命令编排
│   ├── crawl/               采集：浏览器会话、接口解析、抓取编排
│   ├── engine/              通用异步内核：队列/并发/重试/管道/信号（对标 Scrapy）
│   ├── agents/              工具层（含反爬）+ 可组合 agent：背调取证 / 评分骨架
│   ├── structuring/         结构化：JD 分节/抽取/技能、文本与地址、记录清洗
│   ├── store/               持久化：JSONL 主存、数据集加载、表结构、PostgreSQL
│   ├── providers/           外部数据源：天眼查客户端、spider、管道、背调编排
│   ├── config.py            路径、接口、筛选码、延迟、Ark/PG/天眼查配置
│   ├── filters.py           筛选参数 -> 站点筛选码
│   ├── industry_codes.py    行业码表（由站点探测生成）
│   ├── embedding.py         向量化客户端（Ark doubao-embedding-vision）
│   └── export.py            Excel/CSV 导出
├── tests/                   单元测试（363 条，与包结构对应）
├── scripts/                 一次性脚本，不属于生产路径
│   ├── research/            早期接口探测与反爬调研留档
│   └── anti_detect_check.py 反检测自检
├── db/schema.sql            库结构快照（pg_dump --schema-only）
├── output/                  运行产物（gitignore）
├── .state/                  登录态/密钥（gitignore，含敏感信息）
├── .env.example             凭据模板（复制成 .env，.env 不进版本库）
├── pyproject.toml           依赖、入口点 `boss-crawler`
├── requirements.txt         pip 依赖
└── README.md                使用说明与设计要点
```

## 依赖方向

```
cli → crawl / engine / agents / structuring / store / providers / embedding / export → filters / config
agents → engine（复用 RetryPolicy）/ providers（复用 name_score、parse_profile）
providers → engine（spider 与管道挂在引擎上）
store → structuring（清洗、技能分类）
crawl → filters / config
structuring → （无内部依赖，纯函数）
engine → （无内部依赖，只认 Request/Response/Item 三个契约）
```

规则：**只允许上层依赖下层**；跨子包调用只走门面（`boss_crawler.crawl`、
`boss_crawler.engine`、`boss_crawler.agents`、`boss_crawler.structuring`、
`boss_crawler.store`、`boss_crawler.providers`），不深入内部模块。

`agents` 是个特例：它既依赖 `engine`（重试策略）与 `providers`（名称匹配、
档案解析），又通过 `base.py` 只暴露契约——下游 `cli` 只认 `Agent` 接口，
不认识具体是哪个 agent，所以增删 agent 不影响 `cli`。

## 文档索引

| 文档 | 说明 |
|---|---|
| [desktop-design.md](desktop-design.md) | 桌面端页面框架、路由、IPC 与数据契约（只定结构不定视觉） |
| [app-pipeline.md](app-pipeline.md) | `boss_crawler/app/`：采集→背调→打分→适配度→简历的编排、库表、前端 CLI 契约 |
| [agent-layer.md](agent-layer.md) | `boss_crawler/agents/`：工具层、ToolBox 反爬、ToolAgent、评分框架 |
| [cli.md](cli.md) | `boss_crawler/cli/` |
| [crawl.md](crawl.md) | `boss_crawler/crawl/` |
| [engine.md](engine.md) | `boss_crawler/engine/`（对标 Scrapy 的异步内核） |
| [providers.md](providers.md) | `boss_crawler/providers/`（含 `tyc_cli.py` 免费数据源） |
| [store.md](store.md) | `boss_crawler/store/` |
| [structuring.md](structuring.md) | `boss_crawler/structuring/` |
