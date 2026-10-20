# engine/ — 通用异步采集内核

受 Scrapy 启发，但只保留这个项目真正用得上的部分。**引擎不认识任何业务**：
它只知道 `Request` / `Response` / `Item` 三个契约，所以换数据源、加产物都不用改引擎。

```
engine/
├── __init__.py     门面：导出全部公开名字
├── item.py         Request / Response / Item —— 三个契约
├── settings.py     默认配置 + 覆盖（对标 Scrapy settings）
├── scheduler.py    优先队列 + 去重指纹 + 优雅关闭
├── retry.py        重试判定与指数退避（HTTP 码 + 业务码）
├── downloader.py   异步 HTTP：并发上限、主机限速、AutoThrottle
├── middleware.py   下载器中间件：加头、JSON 解析、日志
├── pipelines.py    Item 管道链（同步/异步都能挂）
├── signals.py      事件钩子（观测不侵入主流程）
├── stats.py        统计与分级日志
├── spider.py       Spider 基类：start_requests + parse
└── engine.py       编排：生产 → 队列 → worker → 下载 → 回调 → 管道
```

## 与 Scrapy 的对应

| Scrapy | 这里 | 差异 |
|---|---|---|
| Engine | `engine.py:Engine` | 收尾条件显式化，见下 |
| Scheduler + dupefilter | `scheduler.py` | 用 `asyncio.PriorityQueue` |
| Downloader / AutoThrottle | `downloader.py` | 按主机限速，自适应间隔 |
| Downloader Middleware | `middleware.py` | 只有三个钩子，够用 |
| Spider | `spider.py` | 回调按 `Request.callback` 名字分发 |
| Item Pipeline | `pipelines.py` | `Item.item_type` 代替多个 Item 类 |
| Signals | `signals.py` | 支持异步回调 |
| Stats / Log | `stats.py` | 增加「按组累加」用于成本统计 |
| Settings | `settings.py` | 大写键 + 属性访问 |
| RetryMiddleware | `retry.py` | **同时看 HTTP 码和 body 里的业务码** |

## 数据流

```
spider.start_requests ──┐
                        ├─> Scheduler（去重/优先级） ─> Worker × N ─> Downloader ─> Response
spider.parse ───────────┘                                                        │
       │                                                                         │
       ├─ 产出 Request ──> 回到 Scheduler（形成链路）                              │
       └─ 产出 Item ────> PipelineManager ──> PostgreSQL                          │
                                                                                 │
                        重试判定 <───────────────────────────────────────────────┘
```

## 三个关键设计

### 1. 收尾条件必须四个都满足

```
生产者结束  AND  队列空  AND  无在飞请求  AND  无待重试
```

少一个都会导致「链路刚产出新请求就被判定结束」。待重试是异步 `sleep` 后重投，
所以单独计数（`_delayed`），不能只看队列长度。

### 2. 重试分两层，但只在一处退避

- **传输层不重试**（`Downloader`）：只把异常转成 `Response.error`；
- **重试统一在引擎**：`RetryPolicy` 决定要不要重投、等多久。

两处都退避的话，实际等待时间会变成两层叠加，难以预测。

业务码也在这里判：天眼查这类接口 HTTP 200 却在 body 里返回 `error_code`，
只看状态码会把「限流」当成功。`spider.should_retry` 可以覆盖，但**引擎始终
强制重试次数上限**，避免业务侧返回 `True` 导致无限重试。

### 3. 失败必须可见

重试用尽时发 `request_gave_up` 信号。否则调用方只会看到「请求数变少了」，
说不清哪家公司、哪个接口、为什么失败。天眼查这条链路上，这一条把
「静默消失的公司」变成了可复核的列表。

## 并发与限速

- `CONCURRENT_REQUESTS`：worker 数量 = 该值 + 1，下载器内部再用信号量精确限流；
- `DOWNLOAD_DELAY`：**同一主机**的最小间隔；
- `AUTOTHROTTLE`：按实测延迟平滑调整间隔（`observe` 用 0.7/0.3 平滑，避免一次
  慢请求把节奏拉到最长）。

## 如何扩展（三种都要不改引擎）

**加一种数据源**：写一个 `Spider` 子类，实现 `start_requests` 和若干 `parse_*`；
在 `Request.callback` 里写方法名即可串成多步链路。

**加一种产物**：定义一个 `item_type` 的新值，写一个 `ItemPipeline` 判断
`item.item_type` 后处理，注册进引擎的 `pipelines=` 列表。

**加一种横切逻辑**（签名、代理、埋点）：写一个 `DownloaderMiddleware`，
实现三个钩子中的一个，放进 `middlewares=` 列表。顺序有意义：请求阶段从上到下，
响应阶段从下到上。

## 测试策略

引擎本身用假 transport 测（`tests/test_engine.py`），完全不联网：

- 去重、优先级、关闭唤醒
- 并发上限（断言 `max_active <= CONCURRENT_REQUESTS`）
- HTTP 码与业务码重试、退避上限、次数用尽后放弃
- 链式请求、管道丢弃、`MAX_ITEMS` 截断
- 信号回调抛异常不影响采集

业务侧（`tests/test_tyc_spider.py`）用「按 URL 路由」的假 transport + 假数据库，
断言请求图形态（每个接口被调用几次）、关系分级、成本累计。
