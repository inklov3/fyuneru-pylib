# Task Queue 使用与设计文档

本文档描述 `fyuneru.task_queue` 的使用方式、核心语义和设计取舍。

## 1. 设计目标

`task_queue` 的目标是提供一个轻量、可组合、可观测的 Redis Streams 任务队列能力：

- API 体验参考 Dramatiq（Actor + send + worker）
- 保持 `fyuneru` 一致的函数式风格（`build_*`、显式错误）
- 默认语义清晰：**至少一次消费**
- 关键状态迁移用 Lua 保证原子性（重试/死信 + ACK）
- payload 使用 dataclass envelope，兼顾传输可读性与程序类型一致性
- 解析异常默认 strict：直接暴露错误，不静默吞掉

## 2. 快速使用

```python
from dataclasses import dataclass

from fyuneru.redis_toolkit import init_client_standalone
from fyuneru.result import unwrap
from fyuneru.task_queue import actor, build_broker


@dataclass(frozen=True)
class Payload:
    item_id: str
    priority: int


redis_client = init_client_standalone(host="localhost", port=6379, db=0)()
namespace = "worker-a:{etl}"
broker = build_broker(
    redis_client=redis_client,
    namespace=namespace,
    group_name="default",
)


@actor(
    broker,
    queue_name="default",
    max_retries=0,
)
def process_item(payload: Payload):
    print(payload.item_id, payload.priority)


unwrap(process_item.send(Payload(item_id="item-1", priority=3)))
unwrap(
    broker.run_worker(
        queue_name="default",
        block_ms=1000,
    )
)
```

## 3. API 概览

核心入口：

- `build_broker(redis_client, namespace, group_name="default", claim_idle_ms=None, xq_stream=None) -> TaskQueueBroker`
- `actor(broker, queue_name="default", max_retries=0)`
- `new_message(queue_name, payload, attempt=0, eta=None) -> TaskMessage`
- `TaskQueueBroker.enqueue(message) -> str`
- `TaskQueueBroker.enqueue_many(messages) -> list[ResultE[str]]`
- `TaskQueueBroker.run_worker(queue_name="default", consumer_name=None, block_ms=1000) -> ResultE[int]`
  - `consumer_name=None` 时回退到环境变量 `HOSTNAME`（K8s 下即 Pod 名），都不存在再回退到 `"worker-1"`

## 4. 消息模型

消息字段（stream entry）包含：

- `id`: 业务消息 id（uuid）
- `payload`: JSON 字符串（envelope）
- `attempt`: 当前尝试次数
- `eta`: 预留字段（当前不做延迟调度）
- `created_at`: 生产时间戳

### payload envelope

传输层统一为可读 JSON：

```json
{
  "payload_type": "your_module.Payload",
  "payload": {
    "item_id": "item-1",
    "priority": 3
  }
}
```

规则：

- actor 函数首个且唯一 payload 参数必须声明为 dataclass 类型
- 生产端必须发送该 dataclass 实例
- 消费端按该 dataclass 还原
- `new_message` 同样仅允许 dataclass payload

## 5. fail-fast 约束（无版本兼容）

当前策略是 fail-fast，不做版本降级兼容：

- 生产阶段：发送 payload 必须与 actor 注解 dataclass 类型一致，不一致立即报错
- 消费阶段：envelope `payload_type` 与函数注解 dataclass 不匹配，立即报错
- 消费阶段：payload 字段与 dataclass 不匹配，立即报错
- 注册阶段：无注解、非 dataclass 注解、参数数量不符合约束，立即报错

这确保问题尽早暴露，不隐藏协议漂移。

## 6. 消费与失败语义

- 消费：`XREADGROUP`
- 成功：执行 handler 后 `XACK`
- 失败：
  - `attempt < actor.max_retries`：重试并 ACK 原消息
  - 否则写入 XQ 并 ACK 原消息

默认配置：

- `actor.max_retries=0`：失败直接进 XQ
- `claim_idle_ms=None`：不做超时消息接管；设置后会先执行 `XAUTOCLAIM` 接管超过空闲阈值的 pending 消息
- `xq_stream=None`：使用默认死信流名

XQ 默认流名：`<namespace>:xq`，也可通过 `build_broker(..., xq_stream="...")` 覆盖。

## 7. 原子性策略（最小 Lua）

为避免边界不一致（如“已 ACK 但未重投/未入 XQ”），关键迁移使用 Lua 原子脚本：

- `retry_and_ack.lua`
  - 同一脚本内完成：`XADD(重试流)` + `XACK(原消息)`
- `xq_and_ack.lua`
  - 同一脚本内完成：`XADD(XQ)` + `XACK(原消息)`

这是一种“最小原子化”方案：

- 覆盖最容易造成真实丢消息的关键边界
- 保持整体实现可维护，不把全链路都塞进单个巨型脚本

## 8. 一致性与业务幂等

队列层保证的是**至少一次**，不是“恰好一次”。

因此业务 handler 仍需自行保证幂等（例如基于 `task_id` 做去重），以避免重复执行副作用。

## 9. strict 模式约定

当前按 strict 约定执行：

- 解析/schema 异常直接失败返回
- 不自动吞异常，不自动伪造补偿行为

这有助于尽早暴露框架或上游数据问题。

## 10. 与 Dramatiq 思路的关系

借鉴点：

- Actor 风格 API
- Redis Lua 脚本保障关键状态迁移原子性

差异点：

- 本实现采用“最小 Lua 脚本集”而非单一大状态机脚本
- 优先维持可读性、可调试性和本库函数式风格一致性
