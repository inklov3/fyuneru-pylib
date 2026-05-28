# fyuneru.redis_toolkit

Redis / RedisCluster 惰性初始化、Set 操作、checkpoint key 计算。

需要：`fyuneru[redis]`

## API

```python
from fyuneru.redis_toolkit import (
    init_client_standalone,
    init_client_cluster,
    init_client_from_config,
    bind_redis_set_writer,
    bind_redis_set_reader,
    bind_redis_set_deleter,
    calculate_checkpoint_key,
)

init_client_standalone(host: str, port: int, db: int, **kwargs) -> Callable[[], Redis]
init_client_cluster(host: str, port: int, **kwargs) -> Callable[[], RedisCluster]

init_client_from_config(config: dict) -> Callable[[], Redis] | Callable[[], RedisCluster]
# 读 config["redis"]。支持 standalone（默认）和 cluster 模式。
# 可选 password 字段会转发给 client。
# 缺 "redis" 段抛 KeyError。

bind_redis_set_writer(client, set_name: str) -> RedisSetWriter
# writer(key: str) -> ResultE[None]   — sadd

bind_redis_set_reader(client, set_name: str) -> RedisSetReader
# reader(key: str) -> ResultE[bool]   — sismember

bind_redis_set_deleter(client, set_name: str) -> RedisSetDeleter
# deleter(key: str) -> ResultE[None]  — srem

calculate_checkpoint_key(workspace: str, label: str) -> str
# 返回 "{workspace}:checkpoint:{label}"
```

## Checkpoint 模式

任务幂等推进的标准做法：set_name 当成 checkpoint 命名空间，key 是 per-payload 唯一标识。

```python
from fyuneru.redis_toolkit import (
    bind_redis_set_writer, bind_redis_set_reader, bind_redis_set_deleter,
    calculate_checkpoint_key,
)
from fyuneru.result import unwrap

ck = calculate_checkpoint_key(workspace="ws-a", label="node-1")
advance = bind_redis_set_writer(redis, set_name=ck)
is_past = bind_redis_set_reader(redis, set_name=ck)
delete  = bind_redis_set_deleter(redis, set_name=ck)

if unwrap(is_past("item-001")):
    return    # 已处理，跳过
do_work("item-001")
unwrap(advance("item-001"))
```

## 关键约束

- 假设 `redis-py >= 5`，不要再写 `bytes` 解码兜底
- `init_client_from_config` 通过 `cluster: true/false` 决定走哪个分支
- Set 操作不支持批量；批量场景自己 pipeline
