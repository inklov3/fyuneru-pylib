# Worker Env 计划

## 1. 目标与边界

本规范定义 `fyuneru.worker` 的 Env 构建能力，用于在分布式流任务中统一初始化基础依赖。

- 仅包含 Env 数据模型、初始化流程、约束与验收标准。
- 不包含生命周期管理（start/serve/shutdown）、任务调度、上下游编排。
- 不包含 broker 初始化与注册。
- 当前仅面向 `task_queue` 使用场景，不涉及 dramatiq 适配。

---

## 2. Env 数据模型

Env 使用 dataclass，允许“按配置存在才构建”的可选字段。

```python
from dataclasses import dataclass
from typing import Any, Callable

from pymongo.database import Database
from redis import Redis
from redis.cluster import RedisCluster

from fyuneru.result import ResultE
from fyuneru.s3_toolkit import ObjectStorageReader, ObjectStorageWriter


@dataclass
class WorkerEnv:
    config: dict[str, Any]
    label: str
    redis_client: Redis | RedisCluster | None
    s3_writer: ObjectStorageWriter | None
    s3_reader: ObjectStorageReader | None
    source_reader: Callable[[str], ResultE[bytes]] | None
    mongo_db: Database | None
    advance_checkpoint: Callable[[str], ResultE[None]] | None
    is_past_checkpoint: Callable[[str], ResultE[bool]] | None
```

字段语义：
- `config`: 全局配置对象。
- `label`: 当前 worker 逻辑标签。
- `redis_client`: 状态存储客户端；配置缺失时为 `None`。
- `s3_writer/s3_reader`: 主对象存储写读能力；配置缺失时为 `None`。
- `source_reader`: 源回退读取能力；仅 `s3_sources` 存在时构建。
- `mongo_db`: MongoDB Database 句柄；配置缺失时为 `None`。
- `advance_checkpoint/is_past_checkpoint`: checkpoint 推进/判断函数；仅 redis 可用时构建。

---

## 3. 初始化流程（必须按顺序）

对齐 `setup_worker_env(label, config)` 语义。

1. 校验基础标识：`workspace`、`label` 非空。
2. 若存在 `redis` 配置：初始化 redis client。
3. 基于 `workspace/label` 计算 checkpoint key。
4. 若 redis 可用：构造 `advance_checkpoint/is_past_checkpoint`。
5. 若存在 `s3` 配置：初始化 s3 client 并构造 `s3_writer/s3_reader`。
6. 若存在 `s3_sources` 配置：构造 `source_reader`。
7. 若存在 `mongo` 配置：初始化 mongo db。
8. 组装并返回 `WorkerEnv`。

说明：`setup_worker_env` 不负责日志初始化，日志由应用入口统一配置。

建议接口：

```python
def setup_worker_env(label: str, config: dict[str, Any]) -> WorkerEnv:
    ...
```

---

## 4. 关键约束（必须保持一致）

### 4.1 Checkpoint 一致性

checkpoint key 统一公式：

```python
def calculate_checkpoint_key(workspace: str, label: str) -> str:
    return f"{workspace}:checkpoint:{label}"
```

`is_past_checkpoint` 与 `advance_checkpoint` 必须使用同一 key 与同一 redis 命名空间。

### 4.2 结果路径规则

统一结果路径函数：

```python
def calculate_result_key(
    workspace: str,
    key: str,
    artifact: str,
) -> str:
    return f"{workspace}/result/{key}/{artifact}.pkl"
```

说明：
- `artifact` 用于支持同一 worker 输出/读取多种结果键。
- 禁止节点自行定义偏离该规则的结果路径。

### 4.3 源回退读取语义

当 `s3_reader(key)` 失败且 `source_reader` 存在时，允许回退读取源数据。

### 4.4 错误显式化

Env 对外暴露的 I/O 能力应返回 `Result` 风格对象或显式抛错，禁止静默失败。

---

## 5. 最小 API

必须提供：

```python
def setup_worker_env(label: str, config: dict[str, Any]) -> WorkerEnv: ...

def calculate_result_key(
    workspace: str,
    key: str,
    artifact: str,
) -> str: ...

def calculate_checkpoint_key(workspace: str, label: str) -> str: ...
```

推荐提供（放在 `mongo_toolkit`）：

```python
def bind_collection(db, name: str): ...

def ensure_index(
    collection,
    name: str,
    keys: list[tuple[str, int]],
    unique: bool = False,
    sparse: bool = False,
    background: bool = True,
) -> ResultE[str]: ...
```

约束：
- `ensure_index` 若同名索引存在且 `keys/unique/sparse` 与期望不一致，应立即报错（fail-fast）。
- `background` 不参与冲突判定。

### 5.1 使用方法

```python
from functools import partial

from fyuneru.result import unwrap
from fyuneru.worker import calculate_result_key, setup_worker_env
from fyuneru.mongo_toolkit import bind_collection, ensure_index

config = {
    "workspace": "ws-a",
    "redis": {"host": "127.0.0.1", "port": 6379, "db": 0},
    "s3": {
        "endpoint": "https://s3.example.com",
        "access_key_id": "ak",
        "secret_access_key": "sk",
        "bucket": "media-bucket",
    },
    "mongo": {"uri": "mongodb://127.0.0.1:27017", "db": "fyuneru"},
}

env = setup_worker_env(label="node-demux", config=config)

result_key_builder = partial(
    calculate_result_key,
    workspace=config["workspace"],
)

result_key = result_key_builder(
    key="unit-001",
    artifact="transcript",
)

if env.mongo_db is not None:
    collection = bind_collection(env.mongo_db, "media_results")
    unwrap(
        ensure_index(
            collection,
            "idx_key",
            [("key", 1)],
            unique=False,
        )
    )
```

说明：
- 若配置中缺失 `redis/s3/mongo/s3_sources`，对应 `WorkerEnv` 字段会是 `None`。
- `source_reader` 仅在 `s3_sources` 存在时构建。
- checkpoint key 固定为 `workspace:checkpoint:label`。

---

## 6. 实施计划（落盘版）

### 6.1 范围收敛

- 仅实现 `fyuneru.worker` 的 Env 构建。
- 不实现生命周期层。
- 不实现 broker 封装。

### 6.2 文件级改动

1. 新增 `src/fyuneru/worker/types.py`
   - 定义 `WorkerEnv` dataclass（可选资源字段）。

2. 新增 `src/fyuneru/worker/env.py`
   - 实现 `setup_worker_env(label, config)`。
   - 实现 `calculate_result_key(workspace, key, artifact)`。
   - 做 `workspace/label` 参数校验。

3. 新增 `src/fyuneru/worker/__init__.py`
   - 导出 `WorkerEnv`、`setup_worker_env`、`calculate_result_key`。

4. 修改 `src/fyuneru/redis_toolkit.py`
   - checkpoint 计算函数签名改为 `workspace/label`。

5. 修改 `src/fyuneru/mongo_toolkit.py`
   - 新增 `bind_collection`。
   - 新增 `ensure_index`（同名索引定义冲突立即报错）。

6. 修改 `src/fyuneru/GUIDE.md`
   - 补充 `worker` 包使用说明。
   - 更新 checkpoint 与 result key 语义。

7. 更新 `docs/worker_env_plan.md`
   - 与当前决策保持一致。

### 6.3 实施顺序

1) 先落 `worker` 数据模型与构建函数。  
2) 再改 redis checkpoint 新签名。  
3) 再补 mongo toolkit 两个工具函数。  
4) 最后补文档与测试。

---

## 7. 测试计划

新增 `test/test_worker_env.py`，覆盖：

- `setup_worker_env` 在最小配置下可构建成功。
- redis/s3/mongo/s3_sources 缺失时对应字段为 `None`。
- 配置存在时对应字段可用。
- checkpoint key 为 `workspace:checkpoint:label`。
- result key 为 `{workspace}/result/{key}/{artifact}.pkl`。

新增或补充 mongo 测试：

- `bind_collection` 返回目标 collection。
- `ensure_index`：索引不存在时创建；同名且定义一致时复用；同名但定义冲突时报错。

---

## 8. 与 task_queue 设计一致的约束补充

参考 `docs/task_queue_design.md`，Env 层补充以下一致性原则：

- 保持 fail-fast：配置缺失、类型不匹配、关键字段非法时应立即失败。
- 保持 strict：不做静默兜底，不自动推断缺失配置。
- 保持最小职责：Env 只负责依赖构建，不承担消费循环与任务状态机。
- 保持可组合：返回显式字段与闭包能力，供业务端按需拼装。

---

## 9. 验收清单

复现完成需满足：

- 能创建 `WorkerEnv` 且字段符合“存在才构建”规则。
- `calculate_checkpoint_key` 与新层级公式一致。
- `calculate_result_key` 支持同一 worker 多 artifact。
- `source_reader` 仅在 `s3_sources` 存在时构建。
- Env 不包含 broker 与生命周期控制逻辑。
- `ensure_index` 行为符合“同名索引定义冲突 fail-fast”的约束。
