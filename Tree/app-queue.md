# 任务队列与重试（对标 Scrapy）

## 为什么加

背调阶段原来是两层 `for`：

```python
for company in companies:          # N 家
    for platform in platforms:     # 4 个平台
        await run_agent(...)       # 串行
```

后果有两个：总耗时是**所有任务之和**（4 个平台就是 4 倍），
而且任何一个平台被限流，整段就卡在那一行。

Scrapy 处理这个问题的方式是 **Scheduler + RetryMiddleware + CONCURRENT_REQUESTS**。
这里把那套搬过来，作用在 agent 任务上。

## 模块

`boss_crawler/app/queue.py`

| 类 | 职责 | Scrapy 对应 |
|---|---|---|
| `TaskQueue` | 并发调度、去重、结果收集 | Scheduler + Engine |
| `RetryPolicy` | 退避算法、判定哪些异常值得重试 | RetryMiddleware |
| `TaskResult` | 单个任务的结局（ok/error/attempts/elapsed） | — |

## 三个保留的特性

**1. 并发上限**：`workers` 控制同时在飞的任务数。
不是越大越好——4 个平台同时打，账号更容易被风控，默认 3。

**2. 去重**：同一个 key 在排队/执行中不重复入队。
键是 `agent:公司`，所以「同一家公司同一个平台」天然只跑一次。

**3. 指数退避 + 抖动**：

```
delay = min(base * factor ** (attempt-1), max_delay) * (1 ± jitter)
```

抖动很关键：没有它，被限流的任务会在同一时刻齐刷刷重试，等于自己打自己。
默认 `base=0.4, factor=2, max=8, jitter=0.25`。

## 刻意没做的事

- **不引入 Celery/Redis**：这是单进程本地工具，外部 broker 只会让"跑起来"变复杂；
- **不做分布式**：没有多机需求，优先级队列 + asyncio 足够；
- **不重试所有异常**：`retry_on` 可指定，参数错误这类重试一万次也不会好。

## 参数

```powershell
python -m boss_crawler app run --concurrency 3 --retries 3 --task-timeout 120
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--concurrency` | 3 | 同时在飞的 agent 任务数 |
| `--retries` | 3 | 单个任务最多尝试几次（含首次） |
| `--task-timeout` | 120 | 单个任务超时秒数 |

## 事件

队列事件会被翻译成流水线事件，**重试必须让人看见**——否则用户只会觉得"慢"：

```
! zhihu: 第 1 次尝试失败，0.4s 后重试：RuntimeError: HTTP 429
```

## 实测

```
* backduty [done] 3 家公司，证据 0 条，并发 3，重试 0 次
完成：{'companies': 3, 'queue': {'workers': 3, 'max_attempts': 2,
      'submitted': 3, 'succeeded': 3, 'failed': 0, 'retried': 0, ...}}
```

`summary["queue"]` 会进运行记录，事后能看出「这次重试了几次、超时几次」。

## 测试

`tests/test_queue.py`（17 条）覆盖：重试成功、重试用尽、不可重试异常、
退避上限、抖动范围、去重、并发上限、优先级顺序、超时、事件、坏事件处理器。
