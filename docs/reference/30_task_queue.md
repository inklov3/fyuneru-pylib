# fyuneru.task_queue

基于 Redis Streams 的任务队列：broker、actor 注册、消息投递、worker 消费。

需要：`fyuneru[pipeline]`

设计文档（含语义讨论）：`docs/task_queue_design.md`

## API

```python
from fyuneru.task_queue import (
    build_broker,
    actor,
    new_message,
    BrokerHooks,
)

build_broker(
    redis_client: Redis | RedisCluster,
    namespace: str,
    group_name: str = "default",
    claim_idle_ms: int | None = None,
    xq_stream: str | None = None,
    xq_maxlen: int | None = None,
    hooks: BrokerHooks | None = None,
) -> TaskQueueBroker
# namespace 用来隔离 stream / xq 前缀。
# xq_maxlen 设上限后，xq 流走近似 trim（XADD MAXLEN ~ N），避免无限增长。
# hooks 注入可观测性回调（见下方 BrokerHooks）。

actor(broker, queue_name: str = "default") -> Callable[[TaskHandler], RegisteredActor]
# 装饰器；注册 handler，返回带 .send(payload) 的 actor 对象。
# Handler 必须**仅声明一个**位置 payload 参数，且类型注解必须是 dataclass。
# 一个 queue 只能注册一个 actor；重复注册立即 raise ValueError。

new_message(queue_name: str, payload: Any) -> TaskMessage
# payload 必须是 dataclass 实例。

TaskQueueBroker.enqueue(message: TaskMessage) -> str
# 入队，返回 message id。

TaskQueueBroker.enqueue_many(messages: list[TaskMessage]) -> list[ResultE[str]]
# 批量入队；返回 per-message ResultE 列表。
# 客户端支持 pipeline 时按 stream 分桶后 pipeline 一次提交；
# Cluster 模式下不同 slot 的 stream 不能进同一 pipeline，所以按 stream 分桶后再 pipeline。

TaskQueueBroker.run_worker(
    queue_name: str = "default",
    consumer_name: str | None = None,
    block_ms: int = 1000,
    should_stop: Callable[[], bool] | None = None,
) -> int
# 消费并执行任务；成功后 ack。返回本次循环已处理消息数（执行 / 进 xq 各算一次）。
# consumer_name=None 时回退到 env HOSTNAME（K8s Pod 名），都没有再回退到 "worker-1"。
# 单条消息异常 / Redis 抖动均被吞掉，worker 不会因此退出。
# Redis 连接错误走指数退避（base 0.5s，max 30s）后继续。
# should_stop 由调用方注入 SIGTERM 处理（库不夺信号），主循环每轮入口检查。
# 失败处理：handler 抛错 / payload 校验失败 / actor 未注册 → 一律进 xq（无内置重试）。
```

## Envelope schema

`TaskMessage.payload` 在 Redis 中以 envelope 形式存储：

```python
{
    "payload_type": "your_module.YourDataclass",
    "payload": { ... },
}
```

校验在 `fyuneru.task_queue.codec` 完成；以下三类失败 fail-fast：
- producer payload type 与 actor 声明类型不匹配
- envelope `payload_type` 与本地 dataclass 不匹配
- dataclass 字段不匹配

## Observability hooks

```python
from fyuneru.task_queue import BrokerHooks

hooks = BrokerHooks(
    on_enqueue=lambda queue: ...,                  # 入队
    on_handle_start=lambda queue: ...,             # handler 开始执行
    on_handle_success=lambda queue, elapsed: ...,  # 成功
    on_handle_xq=lambda queue, error: ...,         # 进 xq
    on_redis_error=lambda error: ...,              # Redis 读取异常
)
broker = build_broker(redis_client, namespace="my-ns", hooks=hooks)
```

任何 hook 内抛错都被 broker 吞掉并 warning，绝不反过来杀 worker。

## 语义保证（重要）

- **at-least-once**：handler 在 actor 异常 / Redis 故障两种情况下都可能被重复执行
- **handler 必须幂等**
- 推荐用 `fyuneru.redis_toolkit.calculate_checkpoint_key` + `bind_redis_set_reader/writer` 做 per-payload-key 的幂等检查（见 `20_redis_toolkit.md` 的 checkpoint 模式）

## 滚动发布 schema 兼容性

actor 未注册 / payload 不匹配等"schema 错位"**静默进 xq**（不杀 worker）。这是避免单条坏消息卡死队列的必要妥协，但意味着滚动期间——producer 已升级、consumer 还是旧版——valid 消息会被旧 worker 当成"坏消息"丢进 xq。

两条防线：
1. **部署顺序**：先发 consumer，再发 producer。任何向前兼容增量都安全。
2. **监控**：用 `on_handle_xq` 按 `error` 类型分桶，把 `ValueError("payload 字段与 dataclass 不匹配")`、`KeyError("actor 未注册")` 与"actor 抛错"分开告警。

## 关键约束（写代码前必看）

- handler 签名硬规则：**一个位置参数 + dataclass 类型注解**，多于一个 / 非 dataclass 立即 raise
- **一个 queue 只能一个 actor**，没有 actor name 机制（早期重构已移除）
- 没有内置 retry / eta 延迟；至少一次 + 死信流 (xq) 就是全部
- 本地测试时不要直接调 `run_worker`（无限循环）；用 `run_worker_once_for_test`
