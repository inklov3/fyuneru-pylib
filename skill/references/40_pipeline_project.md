# fyuneru pipeline 项目搭建

本参考用于下游项目用 `fyuneru.task_queue` + `fyuneru.worker.WorkerEnv` 搭建 Redis Streams pipeline。原则：默认按多节点 pipeline 骨架搭建；单节点也使用同一骨架，只是当前只注册一个节点。

## 适用场景

- 项目有一个或多个异步节点，节点间通过 Redis Streams 串联。
- 需要复用 Redis / S3 workspace / `blob://` source reader / Mongo / checkpoint。
- 后续会扩展节点，即使当前只有单节点，也应先按多节点结构落地。

## 推荐目录结构

```text
src/
  pipeline/
    __init__.py
    cli.py              # 公共 CLI 参数 + read_config + setup_worker_env
    contracts.py        # 所有队列 payload dataclass
    registry.py         # build_pipeline(env, ...)：构建 broker 并注册全部 actor
    <node>_node.py      # 单节点业务编排：只接收 payload + WorkerEnv + 可注入纯函数
  pyproject/
    ...                 # 纯业务函数、常量、领域模型
worker/
  main.py               # 统一 worker 入口：--node <node>
script/
  enqueue_<task>.py     # producer / 批量入队脚本
```

规则：
- `src/pyproject` 放纯业务能力，不直接创建 broker / worker。
- `src/pipeline` 放 fyuneru 装配层，负责 `WorkerEnv`、broker、actor、节点串联。
- `worker/main.py` 是唯一 worker 入口，通过 `--node <node>` 选择消费哪个 queue。
- payload 必须是 dataclass，集中放在 `pipeline/contracts.py`。

## pyproject 依赖

按实际资源显式启用 extra。pipeline 项目通常至少需要：

```toml
dependencies = [
    "fyuneru[mongo,pipeline,s3]>=0.1.0",
]
```

如果只用 Redis 队列但不用 S3 / Mongo，也必须包含 `pipeline`；不要假设可选依赖已安装。

## 配置要求

`setup_worker_env(label, config)` 要求 config 至少带：

```yaml
workspace: my-workspace
task: my-task
redis:
  host: localhost
  port: 6379
s3:
  endpoint: https://s3.example.com
  access_key_id: xxx
  secret_access_key: xxx
  bucket: output-bucket
mongo:
  uri: mongodb://localhost:27017
  db: my-db
s3_sources:
- source_id: input
  endpoint: https://s3.example.com
  bucket: input-bucket
  access_key_id: xxx
  secret_access_key: xxx
```

`workspace` 和 `task` 可以由 CLI 注入到 `read_config(...)` 返回的 dict；不要把这两个概念写死在节点函数里。

## cli.py 模式

```python
from __future__ import annotations

import argparse
from pathlib import Path

from fyuneru.config import read_config
from fyuneru.logger import LogLevel, configure_logger
from fyuneru.result import unwrap
from fyuneru.worker import WorkerEnv, setup_worker_env


def parse_common_args(
    description: str,
    *,
    require_node: bool = False,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, default=Path("config.yml"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--group", default="default")
    parser.add_argument("--claim-idle-ms", type=int, default=None)
    parser.add_argument("--consumer", default=None)
    parser.add_argument("--block-ms", type=int, default=30000)
    parser.add_argument("--log-level", default=LogLevel.INFO)
    if require_node:
        parser.add_argument("--node", required=True)
    return parser.parse_args()


def setup_pipeline_env(label: str, args: argparse.Namespace) -> WorkerEnv:
    unwrap(configure_logger(level=args.log_level))
    config = read_config(args.config)
    config["workspace"] = args.workspace
    config["task"] = args.task
    return setup_worker_env(label, config)
```

## contracts.py 模式

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InputTask:
    blob_uri: str


@dataclass(frozen=True)
class NextTask:
    blob_uri: str
```

约束：
- actor handler 必须且仅有一个位置参数。
- 参数类型必须是 dataclass。
- dataclass 字段变更会影响 Redis 中 envelope 解码；发布顺序应先 consumer 后 producer。

## registry.py 模式

```python
from __future__ import annotations

from dataclasses import dataclass

from fyuneru.task_queue import RegisteredActor, TaskQueueBroker, actor, build_broker
from fyuneru.worker import WorkerEnv
from loguru import logger

from pipeline.contracts import InputTask, NextTask
from pipeline.first_node import run_first
from pipeline.second_node import run_second


@dataclass(frozen=True)
class Pipeline:
    broker: TaskQueueBroker
    first: RegisteredActor
    second: RegisteredActor


def build_pipeline(
    env: WorkerEnv,
    *,
    group_name: str,
    claim_idle_ms: int | None,
) -> Pipeline:
    if env.redis_client is None:
        raise RuntimeError("redis_client 未初始化：config 缺少 redis")

    namespace = f"{env.config['workspace']}:{env.config['task']}"
    broker = build_broker(
        redis_client=env.redis_client,
        namespace=namespace,
        group_name=group_name,
        claim_idle_ms=claim_idle_ms,
    )

    @actor(broker=broker, queue_name="second")
    def second(payload: NextTask) -> None:
        run_second(payload, env)

    @actor(broker=broker, queue_name="first")
    def first(payload: InputTask) -> None:
        next_task = run_first(payload, env)
        unwrap(second.send(next_task))

    logger.info("pipeline.actors_registered queues=first,second")
    return Pipeline(broker=broker, first=first, second=second)


def queue_for_node(node: str) -> str:
    queues = {
        "first": "first",
        "second": "second",
    }
    try:
        return queues[node]
    except KeyError as error:
        raise ValueError(f"未知 pipeline node: {node}") from error
```

要点：
- registry 统一注册所有 actor，保证某个 worker 收到下游 queue 也能识别 envelope。
- `queue_for_node` 是部署入口和 queue 名之间的唯一映射；不要把映射散落到 worker 脚本。
- 单节点项目同样保留 `Pipeline` dataclass 和 `queue_for_node`，只是当前映射只有一个节点。
- namespace 必须稳定；推荐由 `workspace` + `task` 组成。
- 当前 task_queue 没有 actor name / retry 参数；不要传 `name=` 或 `max_retries=`。

## node 模式

```python
from __future__ import annotations

from fyuneru.result import unwrap
from fyuneru.worker import WorkerEnv
from loguru import logger

from pipeline.contracts import InputTask, NextTask


def run_first(task: InputTask, env: WorkerEnv) -> NextTask:
    if env.source_reader is None:
        raise RuntimeError("source_reader 未初始化：config 缺少 s3_sources")
    if env.s3_writer is None:
        raise RuntimeError("s3_writer 未初始化：config 缺少 s3.bucket")
    if env.mongo_db is None:
        raise RuntimeError("mongo_db 未初始化：config 缺少 mongo")
    if env.is_past_checkpoint is None or env.advance_checkpoint is None:
        raise RuntimeError("checkpoint 未初始化：config 缺少 redis")

    if unwrap(env.is_past_checkpoint(task.blob_uri)):
        logger.info("first.skip 已有 checkpoint")
        return NextTask(blob_uri=task.blob_uri)

    data = unwrap(env.source_reader(task.blob_uri))
    # 调用纯业务函数，写 S3/Mongo 等副作用
    unwrap(env.s3_writer("result/key", data))
    unwrap(env.advance_checkpoint(task.blob_uri))
    return NextTask(blob_uri=task.blob_uri)
```

规则：
- 节点函数入口固定为 `payload + WorkerEnv`。
- 使用 `env.*` 前先显式 None 检查；`setup_worker_env` 不会因缺配置段自动失败。
- 所有 `ResultE` 用 `unwrap()` 或 `is_failure()` 处理，不要直接读 `.value`。
- handler 是 at-least-once，必须用 checkpoint 或业务唯一键保证幂等。

## worker 入口模式

统一使用 `worker/main.py`，通过 `--node <node>` 选择消费哪个 queue。不要为每个节点新增一个 worker 文件。

```python
from __future__ import annotations

from loguru import logger

from pipeline.cli import parse_common_args, setup_pipeline_env
from pipeline.registry import build_pipeline, queue_for_node


def main() -> None:
    args = parse_common_args("运行 pipeline 队列消费者", require_node=True)
    env = setup_pipeline_env(args.node, args)
    pipeline = build_pipeline(
        env,
        group_name=args.group,
        claim_idle_ms=args.claim_idle_ms,
    )
    queue_name = queue_for_node(args.node)
    logger.info(
        "worker.entering_run_worker node={} queue={}",
        args.node,
        queue_name,
    )
    pipeline.broker.run_worker(
        queue_name=queue_name,
        consumer_name=args.consumer,
        block_ms=args.block_ms,
    )


if __name__ == "__main__":
    main()
```

启动示例：

```bash
uv run python worker/main.py --workspace my-workspace --task my-task --node first
uv run python worker/main.py --workspace my-workspace --task my-task --node second
```

`run_worker` 返回 `int`，不是 `ResultE`；不要 `unwrap(pipeline.broker.run_worker(...))`。

## producer / enqueue 模式

单条入队优先用 actor 的 `.send()`：

```python
message_id = unwrap(pipeline.first.send(InputTask(blob_uri=args.blob_uri)))
```

批量入队可用 `new_message` + `broker.enqueue_many(...)`，逐条检查 `is_failure(result)`。

## 从旧项目迁移时的禁止项

不要照搬这些历史包袱：

- 不要新增 `_fyuneru_patch.py`；当前 fyuneru 已兼容 redis-py 返回结构。
- 不要在 `@actor(...)` 上传 `name=` 或 `max_retries=`；当前 API 不支持 actor name / retry。
- 不要 `unwrap(broker.run_worker(...))`；`run_worker` 直接返回 int。
- 不要新增 `worker/<node>.py` 文件；统一使用 `worker/main.py --node <node>`。
- 不要把 broker 构建散落在 worker 脚本；统一放 `pipeline/registry.py`。
- 不要让业务函数直接依赖全局 config；config 只在 CLI/env 装配层读取。

## 验证建议

下游项目完成改动后至少运行：

```bash
uv run ruff check .
uv run pyrefly
```

如项目有节点纯函数测试，优先测试 `<node>_node.py` 中的 `run_<node>`，不要在单元测试里直接跑无限循环的 `run_worker`。
