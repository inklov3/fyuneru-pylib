# fyuneru.dramatiq_toolkit

Dramatiq RedisBroker 工具：批量投递辅助。

需要：`fyuneru[pipeline]`

## API

```python
from fyuneru.dramatiq_toolkit import enqueue_many, new_message, send_message

enqueue_many(broker: Broker, messages: list[Message]) -> EnqueueManyResult
# Dramatiq 批量入队辅助。
# 返回 success_count / failure_count / failures[(index, error)]。
```

## 关键约束

- 这是给已经用 Dramatiq 的旧代码的兼容层；新项目优先用 `fyuneru.task_queue`（见 `30_task_queue.md`）
- 不要把 `fyuneru.task_queue` 的 actor / broker 与本模块混用
