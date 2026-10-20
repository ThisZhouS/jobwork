# providers/ — 外部数据源（天眼查背调）

职责：把我们库里只有「公司名」的公司，补成有工商档案、母子关系、风险记录的实体。

```
providers/
├── __init__.py     门面：导出下面几个模块的公开名字
├── tianyancha.py   HTTP 客户端：鉴权、限流、重试、错误码、成本记账（按次计费）
├── tyc_cli.py      天眼AI CLI 适配：免费额度、工具分层、错误归一（不花钱）
├── relations.py    纯函数：把 1001 的返回拆成档案 / 关系 / 风险
└── dd.py           编排：读库 → 查询 → 写库（含预算控制）
```

## 两条数据路线

| | `tianyancha.py`（api） | `tyc_cli.py`（cli） |
|---|---|---|
| 通道 | `open.api.tianyancha.com` | 本地 `tyc` 命令（npm 包 tyc-cli） |
| 计费 | 按次，¥0.15–6/次 | 免费会员额度 |
| 门槛 | 需充值（最低 100，最高档 1000） | 只需 `tyc login`（OAuth） |
| 关系明细 | 有（对外投资/分支等） | VIP 工具，免费拿不到 |
| 风险明细 | 有 | 只有概览计数 |

`tyc_cli.py` 里用 `FREE_TOOLS` / `VIP_TOOLS` 两个集合把工具分层固化下来，
调用免费工具之外的任何东西都会被发现（测试里有一条断言专门守这个）。
它**不替调用方做降级**：拿不到就抛 `TycCliError`，由上层决定是跳过还是报错。

## 为什么这么分层

- `tianyancha.py` 只管「把请求发出去、把 `result` 拿回来」。它不知道
  `result` 里有什么，也不知道数据库长什么样。
- `relations.py` 只管「把 JSON 变成结构化的行」。不联网、不碰数据库，
  所以能用录制的样例做完整回归测试。
- `dd.py` 只管「先查谁、花多少钱、写到哪」。预算、阈值、深度都在这一层。

好处：换数据源（爱企查/企查查）只需再写一个 client + parser，
`dd.py` 的编排逻辑可以照用。

## 关键设计

### 名称匹配

BOSS 上的公司名大量是简称（`茶百道` → `四川茶百道实业股份有限公司`），
直接查会大面积落空。`dd.py:name_score` 给可解释的分数：

| 情况 | 分数 |
|---|---|
| 完全相同 | 1.0 |
| 互相包含 | 0.75 ~ 1.0（按字符重叠度加成） |
| 无关 | 公共字符比例，通常 < 0.2 |

低于 `DueDiligenceOptions.resolution_threshold`（默认 0.85）会写进
`match_note`，标成「需人工确认」而不是静默采信。

优先用 `legal_name`（工商全称）去查，命中率明显高于 BOSS 展示名。

### 关系方向与概念区分

`1001` 一次返回三个方向的边：

| 字段 | relation | 含义 |
|---|---|---|
| `headquarters` | `parent` | 总公司（工商登记隶属，通常即母公司） |
| `investList` | `subsidiary` | 对外投资，**不等于子公司** |
| `branchList` | `branch` | 分支机构（分公司，非独立法人） |

`investList` 里可能是 5% 的财务投资，所以按 `percent` 分级：

- `100%` → 全资子公司
- `> 50%` → 控股子公司（真子公司）
- `≥ min_percent`（默认 20%）→ 参股公司
- 低于 20% → 写作「财务投资」，不入库（避免把理财式持股当关联方）

### 成本控制

`1001` 自带经营异常/严重违法/行政处罚清单，**这三类不额外花钱**；
只有失信人、被执行人需要单买（各 ¥0.15）。关联方风险也只查这两项。

按页面标价（2026-10 实测）：

| 接口 | 用途 | 单价 |
|---|---|---|
| 816 搜索 | 名称 → 实体 | ¥0.01 |
| 1001 工商全景 | 档案 + 关系 + 三类风险 | ¥1.00 |
| 843 失信人 | 自身/关联方 | ¥0.15 |
| 839 被执行人 | 自身/关联方 | ¥0.15 |

每家固定 ¥1.31；每查一家关联方的风险再 ¥0.30。
`--max-cost` 是硬上限，跑到就停，不会失控。

## 数据落库

四张表（`store/schema.py`）+ 一个汇总视图：

| 表 | 内容 |
|---|---|
| `tyc_company` | 工商档案，一公司一行，原始 JSON 存 `raw` |
| `tyc_relation` | 关系边，含 `percent`/`grade`/`depth` |
| `tyc_risk` | 风险事件，`relation` 区分 self/parent/subsidiary |
| `tyc_fetch_log` | 每次调用的接口、错误码、耗时、价格 |
| `tyc_dd_overview`（视图） | 一公司一行：关系数 + 自身/母公司/子公司风险数 |

`tyc_risk.related_key` 是「这笔风险算在谁头上」：子公司的失信记录
`related_key` 仍是我们的 `company_key`，`relation='subsidiary'`，
这样一句 SQL 就能回答「这家公司连同它的母子公司有没有雷」。

重跑幂等：`replace_tyc_relations` / `replace_tyc_risks` 先删后插，
`tyc_company` 用 `ON CONFLICT` upsert，重复跑不会产生重复行。

## 凭据

token 只从环境读，两种来源（优先级从高到低）：

1. `.env` 的 `TIANYANCHA_TOKEN`（`.env.example` 是模板）
2. `.state/tyc_token.txt`

`.env` 已在 `.gitignore` 里。代码里没有任何硬编码 token。

缺少 token 时命令以退出码 3 结束，并给出明确提示，不会静默跳过。

## 扩展位置

- 想加新接口（如股权穿透 455）：在 `config.TYC_API`/`TYC_PRICES` 加一行，
  在 `TianyanchaClient` 加一个便捷方法，在 `relations.py` 加 parser。
- 想换数据源：新建 `providers/<vendor>.py`，实现同样的
  `search/get_*` 接口，`dd.py` 的编排可复用。
- 想调风险判定规则：改 `relations.py:verdict`，它是纯函数，好测。
