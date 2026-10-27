# 求职工作台 JobsDesktop

本地优先的个人求职工作台：从职位采集到定向简历，一条链路在本机完成。
以 **Windows x64 携带版**（单个 exe）分发，复制即用，不写注册表；
数据默认全部落在本机，只有启用 AI 摘要 / 润色时，相关文本才会发送到你配置的模型服务。

## 功能概览

- **职位采集**：按岗位、城市、薪资、经验、学历、行业筛选，采集职位列表与详情，自动限速
- **结构化清洗**：JD 分节、技能/福利抽取、公司名规范化、地址拆解，导出 Excel / CSV
- **公司背调**：工商档案、风险记录、母子公司关系；免费渠道优先，付费接口可选且带预算上限
- **多维打分**：公司（风险/待遇/压力/环境/福利）与岗位适配度（岗位 × 简历）规则打分，可选模型复核
- **定向简历**：基于岗位要求重排已有事实，经你确认后才生成新版本
- **语义检索**：PostgreSQL 向量检索（技能、职责语义匹配），不依赖外部检索服务
- **配置中心**：模型接口、密钥、数据商凭据全部图形化配置；密钥只写不读，界面不回显明文

## 快速开始（用户）

### 1. 下载与运行

从 Releases 下载 `JobsDesktop-Portable-x64.exe`，复制到任意目录直接双击运行。
不需要管理员权限，不写注册表。**升级**时关闭应用、替换 exe 即可，配置与登录态保留。

### 2. 运行前提

携带版只打包 Electron 壳与源码，运行环境需要自行准备：

| 依赖 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 x64 |
| Python | 3.10+；默认调用 `python`，也可用环境变量 `PYTHON` 指向任意解释器 |
| Python 依赖 | 在目标解释器里执行 `uv sync`（或 `pip install -r requirements.txt`） |
| 采集浏览器 | 首次使用前执行 `uv run patchright install chromium` |
| PostgreSQL | 可访问的实例，已建库，并准备好连接密码 |

推荐把依赖装进独立虚拟环境，启动前把 `PYTHON` 指过去：

```powershell
uv sync
$env:PYTHON = "$PWD\.venv\Scripts\python.exe"
.\desktop\dist\JobsDesktop-Portable-0.3.0-x64.exe
```

数据库连接使用 `PGHOST` / `PGPORT` / `PGUSER` / `PGDATABASE` / `PGPASSWORD` 环境变量；
密码也可以在「配置中心 → 本机凭据」写入本机 `.state`（环境变量优先）。

### 3. 首次启动

1. 确认 PostgreSQL 与 Python 依赖可用后，启动 exe；
2. 首次启动会把内置默认配置复制到数据目录；
3. 打开「配置中心」：
   - **模型规格**：配置模型接口与密钥（用于背调摘要、打分复核、简历润色，可整体关停）；
   - **本机凭据**：填写数据库密码与数据商凭据；
4. 在「平台登录」扫码登录采集平台，然后开始采集。

### 4. 数据目录

| 路径 | 内容 |
| --- | --- |
| `%APPDATA%\JobsDesktop\config` | `agents.json` / `models.json`（可写，升级不覆盖） |
| `%APPDATA%\JobsDesktop\.state` | 登录态、密钥、窗口状态、临时文件 |
| `%APPDATA%\JobsDesktop\.state\model_keys` | 设置页保存的模型密钥（仅本机） |

**卸载**：删除 exe；如需彻底清理，再删除 `%APPDATA%\JobsDesktop`
（会丢失登录态、本地密钥与配置）。应用不写注册表，也没有后台服务。

## 数据与隐私

- **本地优先**：职位数据、登录态、密钥、配置默认全部落在本机（PostgreSQL + 本地文件）；
- **什么会外发**：只有启用 AI 背调摘要、打分复核或简历润色时，相关文本
  （公司名、证据摘要、简历草稿）会发送到「配置中心」里配置的模型服务，可随时关停；
- **密钥安全**：密钥只从环境变量或本机 `.state/` 下的文件读取，绝不写进配置文件、
  日志或命令行参数；设置页对密钥只写不读；
- **凭据优先**：运行期环境变量优先于本机文件，检测到环境变量时界面会标注。

## 合规与许可

本项目是面向个人求职的低频工具：

- 只采集公开可见的职位信息，不复制、不二次分发、不售卖任何站点内容；
- 默认采集频率较保守，单次建议只抓取少量页面；
- 请使用自己的账号登录，不要多人共用同一登录态；
- 若目标站点风控或明确拒绝，应停止采集，而不是加大频率；
- 数据商接口按实际用量计费，调用均带预算上限与留痕，请自行核对账单。

继续使用即表示你自行承担与目标站点服务条款相关的责任。
许可条款见仓库根目录的 `LICENSE` 文件。

## 开发者

### 项目结构

```
boss_crawler/         采集、结构化、持久化与命令行
  structuring/          JD 分节、标量抽取、技能/福利、地址清洗（纯函数，可离线单测）
  crawl/                浏览器会话、页面解析、采集流程与恢复
  store/                JSONL 主存、CSV/Excel 导出、PostgreSQL 建表与写入
  providers/            外部数据源适配器（配置化，不硬编码某家接口）
  agents/               背调/打分/适配度 agent 与工具注册
  cli/                  命令行参数与子命令编排
config/                运行期配置（agents.json / models.json / risk_api.json）
desktop/               Electron 桌面端（main / preload / renderer）
db/schema.sql          库结构快照
tests/                 单元测试（全部离线，不发真实请求）
tools/                 密钥扫描等工程工具
scripts/               调研与自检脚本（一次性留档，不属于生产路径）
```

数据流向：`crawl → store → db → agents（背调/打分）→ app（编排）→ 桌面端只读展示`。
依赖只允许向下，跨子包调用只走包门面。

### 构建桌面端

```powershell
cd desktop
npm install
npm run build:win
# 产物：desktop\dist\JobsDesktop-Portable-x64.exe
```

构建机会把 `boss_crawler/`、`config/`、`db/`、`requirements.txt` 打进 exe 资源目录；
构建机需要 Node.js 18+，运行时机器不需要 Node.js。

### 开发环境与测试

```powershell
uv sync --extra dev                  # 开发依赖（pytest / ruff / mypy）
uv run ruff check .                  # 静态检查（CI 同款）
uv run mypy                          # 类型检查
uv run pytest -q --cov               # 全量单元测试 + 覆盖率（阈值 60%）
uv run python tools/check_secrets.py # 密钥扫描（--all 扫全工作区）
```

测试全部离线：使用合成 HTML/JSON 与假 http/browser，不发真实请求；
密钥扫描器同时被 pytest 调用，误提交密钥会被 CI 拦住。

### 命令行接口（开发者用）

命令行提供完整的采集 / 清洗 / 入库 / 背调 / 编排子命令，主要供开发调试与桌面端
后端调用；**桌面应用是唯一面向用户的入口**，普通用户不需要接触命令行。
全部命令、接口实测记录与深度设计文档见本地 `docs/`（不随仓库发布）：

- `docs/tree/` — 各子包的目录索引与设计说明（原 `Tree/`）；
- `docs/technical-notes.md` — 采集、清洗、背调、评分等技术细节汇总；
- `docs/concepts/` — 界面概念截图。

### 仓库目录约定

| 路径 | 内容 |
| --- | --- |
| `output/` | 采集结果（已忽略，不入库） |
| `.state/` | 本机登录态与密钥（已忽略，敏感） |
| `docs/` | 深度技术文档与界面截图（已忽略，不发布） |
| `config/*.local.json` | 本地覆盖配置（可能含真实凭据，已忽略） |

## 已知限制

- 只覆盖求职者视角的公开页面，未实现沟通、投递等写操作；
- 平台风控是动态的，极端情况下需要人工重新登录；
- 部分数据源需要登录态或付费额度，缺失时程序会明确报缺，不会静默跳过。
