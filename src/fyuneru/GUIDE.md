# fyuneru — API Reference for Claude Code

Python utility library wrapping common infrastructure components with unified, composable functional interfaces. Uses `fyuneru.result` for explicit error handling and lazy client initialization.

## Installation

```bash
uv add fyuneru@git+https://github.com/inklov3/fyuneru-pylib.git

# With optional dependencies
uv add "fyuneru[redis] @ git+https://github.com/inklov3/fyuneru-pylib.git"
uv add "fyuneru[s3] @ git+https://github.com/inklov3/fyuneru-pylib.git"
uv add "fyuneru[mongo] @ git+https://github.com/inklov3/fyuneru-pylib.git"
uv add "fyuneru[pipeline] @ git+https://github.com/inklov3/fyuneru-pylib.git"   # Redis Streams task queue
uv add "fyuneru[media] @ git+https://github.com/inklov3/fyuneru-pylib.git"      # av + Pillow
uv add "fyuneru[gemini] @ git+https://github.com/inklov3/fyuneru-pylib.git"     # Google Gemini
```

## Key Patterns

- **`init_*`** returns a `Callable` that lazily creates a client when called
- **`bind_*`** binds client/resources and returns a single composable operation function
- **`build_*`** builds higher-level composed objects
- **`@safe`** wraps return values in `Result` type; use `unwrap(result)` to extract the value
- **Checkpoint** key follows `workspace/task/label` hierarchy and can be composed with redis set binders or `fyuneru.worker` env setup

## Modules

### logger (`fyuneru.logger`)

```python
from fyuneru.logger import configure_logger, tqdm_loguru, LogLevel

# LogLevel: INFO, WARNING, ERROR, DEBUG

configure_logger(level: str = LogLevel.INFO, log_dir: Path | None = None) -> ResultE[None]
# Decorated with @safe; call unwrap(result) to raise on failure.
# Configures loguru logger with console output + optional file output.
# When log_dir is set, creates timestamped log file and latest.log.
# IMPORTANT: 内部首先调用 logger.remove() 清空所有已注册 handler，
# 重复调用会把日志通道完全重置而非叠加，调用方不要期望"再加一个 sink"语义。

tqdm_loguru(iterable, level="INFO", **tqdm_kwargs) -> tqdm
# tqdm wrapper that outputs progress via loguru instead of stderr.
```

### config (`fyuneru.config`)

```python
from fyuneru.config import (
    parse_mongo_config,
    parse_redis_config,
    parse_s3_config,
    read_config,
    read_config_with_override,
)

read_config(config: Path) -> dict[str, Any]
# Reads YAML config file. Empty file returns {}.
# Raises ValueError for non-mapping root.

read_config_with_override(base: Path, override: Path | None = None) -> dict[str, Any]
# Reads base config and optionally overlays one override YAML.
# Merge rules:
# - dict: recursive merge, override value wins on key conflict
# - scalar: override replaces base
# - list: append (base + override)
# Non-goals: no template rendering, no field deletion semantics.

parse_redis_config(config: dict[str, Any]) -> RedisConfig
parse_s3_config(config: dict[str, Any]) -> S3Config
parse_mongo_config(config: dict[str, Any]) -> MongoConfig
# Typed parser with explicit field validation and path-aware errors.
# parse_s3_config supports optional addressing_style: "virtual" | "path".
```

### converter (`fyuneru.converter`)

```python
from fyuneru.converter import (
    unsafe_object_to_bytes,
    unsafe_bytes_to_object,
    to_json_object,
    NonSerializable,
)

unsafe_object_to_bytes(data: Any) -> bytes        # pickle serialize
unsafe_bytes_to_object(data: bytes) -> Any        # pickle deserialize
# 仅用于完全可信的内部字节流。pickle.load 对外部输入等于 RCE，名字里的 unsafe_
# 就是为了让调用方在 grep 时一眼看到风险。

to_json_object(data: Any) -> Any
# Recursively converts any object to JSON-compatible structure.
# Handles primitives, namedtuples, list/tuple/set/frozenset, dict, objects with __dict__,
# plus datetime/date/time (isoformat), Decimal/UUID/PurePath (str), bytes/bytearray (base64 ascii).
# Fields with NonSerializable values are excluded.
# Raises TypeError for unsupported types.
```

### markdown_utils (`fyuneru.markdown_utils`)

```python
from fyuneru.markdown_utils import unwrap_codeblock

unwrap_codeblock(text: str) -> str
# Strips markdown code block fences, keeps inner content.
# "```python\nprint('hello')\n```" -> "print('hello')\n"
```

### redis_toolkit (`fyuneru.redis_toolkit`)

Requires: `fyuneru[redis]`

```python
from fyuneru.redis_toolkit import (
    bind_redis_set_deleter,
    bind_redis_set_reader,
    bind_redis_set_writer,
    calculate_checkpoint_key,
    init_client_cluster,
    init_client_standalone,
)

init_client_standalone(host: str, port: int, db: int, **kwargs) -> Callable[[], Redis]
init_client_cluster(host: str, port: int, **kwargs) -> Callable[[], RedisCluster]

init_client_from_config(config: dict) -> Callable[[], Redis] | Callable[[], RedisCluster]
# Reads config["redis"]. Supports standalone (default) and cluster mode.
# Optional "password" field is forwarded to the Redis client.
# Raises KeyError if "redis" section missing.

bind_redis_set_writer(client: Redis | RedisCluster, set_name: str) -> RedisSetWriter
# writer(key: str) -> ResultE[None]   — sadd

bind_redis_set_reader(client: Redis | RedisCluster, set_name: str) -> RedisSetReader
# reader(key: str) -> ResultE[bool]   — sismember

bind_redis_set_deleter(client: Redis | RedisCluster, set_name: str) -> RedisSetDeleter
# deleter(key: str) -> ResultE[None]  — srem

calculate_checkpoint_key(workspace: str, task: str, label: str) -> str
# Returns "{workspace}:{task}:checkpoint:{label}"
```

**Checkpoint pattern:**
```python
from fyuneru.result import unwrap

checkpoint_key = calculate_checkpoint_key(workspace="ws-a", task="etl", label="node-1")
advance = bind_redis_set_writer(redis, set_name=checkpoint_key)
is_past = bind_redis_set_reader(redis, set_name=checkpoint_key)
delete = bind_redis_set_deleter(redis, set_name=checkpoint_key)
unwrap(advance("item-001"))
assert unwrap(is_past("item-001")) is True
```

### s3_toolkit (`fyuneru.s3_toolkit`)

Requires: `fyuneru[s3]`

```python
from fyuneru.s3_toolkit import (
    bind_s3_chunked_reader,
    bind_s3_deleter,
    bind_s3_lister,
    bind_s3_reader,
    bind_s3_stream_reader,
    bind_s3_writer,
    init_client,
)

init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config: Config | None = None,    # botocore.config.Config
    addressing_style: str = "virtual",
) -> Callable[[], S3Client]
# Default config: signature_version="s3v4".
# addressing_style supports "virtual" or "path".

init_client_from_config(config: dict) -> Callable[[], S3Client]
# Reads config["s3"]. Returns Callable[[], S3Client].
# Raises KeyError if "s3" section missing.
# 与 init_workspace_from_config 的差别：client 层不需要 bucket，因此本函数不会
# 校验 s3.bucket；只在调用 init_workspace_from_config 时才强制要求 bucket。

init_workspace_from_config(config: dict) -> Callable
# Reads config["s3"] including required "bucket" field.
# Returns Callable[[], tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]].
# 必须含 s3.bucket，缺失立刻抛 KeyError。

bind_s3_writer(client: S3Client, bucket: str) -> ObjectStorageWriter
# writer(key: str, body: bytes) -> ResultE[None]  — put_object

bind_s3_reader(client: S3Client, bucket: str) -> ObjectStorageReader
# reader(key: str) -> ResultE[bytes]               — get_object
# 警告：全量读入内存，不适合大文件，大文件请用 bind_s3_chunked_reader 或
# bind_s3_stream_reader，否则随时会 OOM。

bind_s3_chunked_reader(
    client: S3Client,
    bucket: str,
    chunk_size: int = 1024 * 1024,
) -> ObjectStorageChunkedReader
# reader(key: str) -> ResultE[Iterator[bytes]]
# 按 chunk_size 迭代对象内容，迭代器消费完毕或抛错时自动 close 底层 socket。
# 返回的迭代器只能消费一次。chunk_size 必须 > 0。

bind_s3_stream_reader(
    client: S3Client, bucket: str
) -> ObjectStorageStreamReader
# reader(key: str) -> ResultE[StreamingBody]
# 把 boto3 的 StreamingBody 直接交给调用方，适合需要把 body 转交给非 boto3
# 库（视频解码器等）的场景。调用方必须配合 with closing(body): 使用，避免 socket 泄漏。

bind_s3_deleter(client: S3Client, bucket: str) -> ObjectStorageDeleter
# deleter(key: str) -> ResultE[None]               — delete_object

bind_s3_lister(client: S3Client, bucket: str) -> ObjectStorageLister
# lister(prefix: str, suffix: str | None = None) -> ResultE[list[str]]
# Auto-paginates via list_objects_v2 + ContinuationToken.
# 若服务端返回 IsTruncated=True 但缺 NextContinuationToken，会抛 RuntimeError 并附带 prefix，
# 防止陷入死循环。
# Filters out directory placeholders (keys ending with "/").
# Optional suffix filter applied client-side.
```

### s3_source (`fyuneru.s3_source`)

Requires: `fyuneru[s3]`

通过 `blob://桶id/key` URI 协议透明访问多个 S3 源。

```python
from fyuneru.s3_source import bind_source_reader, load_source_registry, parse_blob_uri

parse_blob_uri(uri: str) -> tuple[str, str]
# Parses "blob://bucket_id/key" -> (bucket_id, key).
# Raises ValueError for invalid format.

load_source_registry(
    config: dict,
) -> dict[str, dict]
# Reads config["s3_sources"] list, validates required fields,
# converts to dict keyed by source_id.
# Raises KeyError if "s3_sources" key is missing.
# Raises ValueError if s3_sources is not a list, any entry is not a dict,
# any required field is missing, or source_id is not a non-empty string.
# When duplicate source_id is found, logs warning and uses later entry to override earlier.

bind_source_reader(registry: dict[str, dict]) -> Callable[[str], ResultE[bytes]]
# Returns a closure that reads from blob:// URIs.
# Lazily initializes S3 clients per bucket_id, caches them.
```

**Usage:**
```python
from fyuneru.config import read_config_with_override
from fyuneru.result import unwrap
from fyuneru.s3_source import bind_source_reader, load_source_registry

config = read_config_with_override(Path("config.yml"))
registry = load_source_registry(config)
read = bind_source_reader(registry)
data = unwrap(read("blob://my-images/photos/img001.jpg"))
```

**Overlay note:**
- For `s3_sources`, `read_config_with_override` keeps append behavior; dedupe by `source_id` is applied in `load_source_registry` (later item wins).

**Config format (main YAML `s3_sources` section):**
```yaml
s3_sources:
- source_id: my-images
  endpoint: https://s3.example.com
  bucket: actual-bucket-name
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1  # optional

- source_id: backup-store
  endpoint: https://s3.backup.com
  bucket: backup-bucket
  access_key_id: xxx
  secret_access_key: xxx
```

### mongo_toolkit (`fyuneru.mongo_toolkit`)

Requires: `fyuneru[mongo]`

```python
from fyuneru.mongo_toolkit import (
    bind_collection,
    ensure_index,
    init_client,
    init_client_from_config,
    init_database_from_config,
)

init_client(uri: str, timeout: int = 10000)
    -> Callable[[], MongoClient]
# timeout is serverSelectionTimeoutMS
# Always returns a MongoClient initializer.

init_client_from_config(config: dict) -> Callable[[], MongoClient]
# Reads config["mongo"]. Returns Callable[[], MongoClient].
# Raises KeyError if "mongo" section missing.

init_database_from_config(config: dict) -> Callable[[], Database]
# Reads config["mongo"] including required "db" field.
# Returns Callable[[], Database].

bind_collection(db: Database, name: str) -> Collection
# Returns db[name] after validating collection name.

ensure_index(
    collection: Collection,
    name: str,
    keys: list[tuple[str, int]],
    unique: bool = False,
    sparse: bool = False,
    background: bool = True,
) -> ResultE[str]
# Creates index when absent.
# If same index name exists but keys/unique/sparse mismatch expected values,
# returns Failure with conflict error.
```

### worker (`fyuneru.worker`)

Requires optional dependencies based on enabled resources (`redis` / `s3` / `mongo`).

```python
from fyuneru.worker import (
    WorkerEnv,
    calculate_checkpoint_key,
    calculate_result_key,
    setup_worker_env,
)

setup_worker_env(label: str, config: dict[str, Any]) -> WorkerEnv
# Builds worker environment with optional resources.
# redis/s3/mongo/source_reader are created only if config sections exist.

calculate_checkpoint_key(workspace: str, task: str, label: str) -> str
# Returns "{workspace}:{task}:checkpoint:{label}".

calculate_result_key(
    workspace: str,
    task: str,
    key: str,
    artifact: str,
) -> str
# Returns "{workspace}/{task}/result/{key}/{artifact}.pkl".
```

### task_queue (`fyuneru.task_queue`)

Requires: `fyuneru[pipeline]`

```python
from fyuneru.task_queue import (
    BrokerHooks,
    actor,
    build_broker,
    new_message,
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
# Builds Redis Streams based task broker.
# xq_maxlen 设上限后，xq 流用近似 trim（XADD MAXLEN ~ N）避免无限增长。
# hooks 注入可观测性回调；详见下方 BrokerHooks。

actor(
    broker: TaskQueueBroker,
    queue_name: str = "default",
) -> Callable[[TaskHandler], RegisteredActor]
# Registers a handler and returns actor object with .send(payload).
# Handler must declare exactly one positional payload parameter annotated as dataclass.
# 一个 queue 只能注册一个 actor；重复注册立即 raise ValueError。

new_message(
    queue_name: str,
    payload: Any,
) -> TaskMessage
# payload must be a dataclass instance.

TaskQueueBroker.enqueue(message: TaskMessage) -> str
# Enqueues message into stream and returns message id.

TaskQueueBroker.enqueue_many(messages: list[TaskMessage]) -> list[ResultE[str]]
# Batch enqueue; returns per-message ResultE list.
# 当 redis 客户端支持 pipeline 时，按 stream 分桶后用 pipeline 一次性提交，
# 将 N 次 RTT 降到 stream 数量级。Cluster 模式下不同 slot 的 stream 不能进同一 pipeline，
# 因此按 stream 分桶后再 pipeline。

TaskMessage.payload uses envelope schema:
# {
#   "payload_type": "your_module.YourDataclass",
#   "payload": { ... }
# }
# Fail-fast: producer payload type mismatch, envelope payload_type mismatch,
# or dataclass field mismatch all raise errors.

TaskQueueBroker.run_worker(
    queue_name: str = "default",
    consumer_name: str | None = None,
    block_ms: int = 1000,
    should_stop: Callable[[], bool] | None = None,
) -> int
# Consumes and executes tasks; acks on success. 返回值是本次循环已处理的消息数量
# （执行 / 进 xq 各算一次）。
# consumer_name=None 时回退到环境变量 HOSTNAME（K8s 下即 Pod 名），
# 都不存在再回退到 "worker-1"。
# 单条消息异常 / Redis 抖动均被吞掉，worker 不会因此退出；
# Redis 连接错误走指数退避（base 0.5s，max 30s）后继续。
# should_stop 由调用方注入 SIGTERM 处理（库不夺取信号），主循环每轮入口检查一次。
# 失败处理：handler 抛错 / payload 校验失败 / actor 未注册 → 一律进 xq（无内置重试）。
```

**Observability hooks（`BrokerHooks`）**：注入零开销的 callback，缺省全部 None。任何 hook
内抛错都会被 broker 吞掉并 warning，绝不会反过来杀掉 worker。

```python
from fyuneru.task_queue import BrokerHooks

hooks = BrokerHooks(
    on_enqueue=lambda queue: ...,                  # 入队
    on_handle_start=lambda queue: ...,             # handler 开始执行
    on_handle_success=lambda queue, elapsed: ...,  # 成功
    on_handle_xq=lambda queue, error: ...,         # 进 xq
    on_redis_error=lambda error: ...,              # Redis 读取异常
)
broker = build_broker(redis_client, namespace=..., hooks=hooks)
```

**语义保证**：fyuneru task_queue 是 **at-least-once**——handler 在 actor 异常 / Redis
故障两种情况下都可能被重复执行。**handler 必须幂等**。
推荐用 `fyuneru.redis_toolkit.calculate_checkpoint_key` + `bind_redis_set_reader/writer`
做 per-payload-key 的幂等检查（jump-cut 的 `is_past_checkpoint` / `advance_checkpoint` 即是此模式）。

**滚动发布的 schema 兼容性**：actor 未注册 / payload 与 dataclass 不匹配等"schema 错位"
失败现在**静默进 xq**而不是杀 worker。这是必要妥协（避免一条坏消息卡死整个队列），
但意味着滚动发布期间——producer 已升级、consumer 还是旧版——valid 消息会被旧
worker 当成"坏消息"丢进 xq。两条防线：
- 部署顺序：先发 consumer，再发 producer。任何向前兼容增量都安全。
- 监控：通过 `on_handle_xq` hook 按 `error` 类型分桶——`ValueError("payload 字段
  与 dataclass 不匹配")`、`KeyError("actor 未注册")` 等都是 schema 错位信号，应该
  与"actor 抛错"分开告警。

### dramatiq_toolkit (`fyuneru.dramatiq_toolkit`)

Requires: `fyuneru[pipeline]`

```python
from fyuneru.dramatiq_toolkit import (
    enqueue_many,
    new_message,
    send_message,
)

enqueue_many(broker: Broker, messages: list[Message]) -> EnqueueManyResult
# Batch enqueue helper for Dramatiq.
# Returns success_count / failure_count / failures[(index, error)].
```

### gemini_toolkit (`fyuneru.gemini_toolkit`)

Requires: `fyuneru[gemini]`

```python
from fyuneru.gemini_toolkit import build_content_config, init_client, init_client_from_config

init_client(api_key: str, endpoint: str, api_version: str = "v1beta")
    -> Callable[[], Client]
# Creates a google.genai.Client with custom endpoint and auth headers.

init_client_from_config(config: dict) -> Callable[[], Client]
# Reads config["llm"]. Currently only supports provider="gemini".
# Raises KeyError if "llm" section missing, ValueError for unsupported provider.

build_content_config(
    schema: dict[str, Any],
    response_mime_type: str = "application/json",
    temperature: float = 0,
    system_instruction: str | None = None,
) -> GenerateContentConfig
# Builds config for structured JSON output from Gemini.
```

**Usage:**
```python
client = init_client(api_key="sk_xxx", endpoint="https://xxx")()
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[prompt],
    config=build_content_config(
        schema=MyModel.model_json_schema(),
        system_instruction=system_prompt,
    ),
)
result = MyModel.model_validate_json(response.text)
```

Task queue design doc: `docs/task_queue_design.md`

## Config YAML Format

```yaml
redis:
  host: localhost
  port: 6379
  db: 0             # optional, default 0
  cluster: false     # optional, default false
  password: xxx      # optional, omit if no auth

s3:
  endpoint: https://s3.example.com
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1     # optional
  bucket: my-bucket          # required by init_workspace_from_config
  addressing_style: virtual  # optional: virtual | path

mongo:
  uri: mongodb://localhost:27017
  db: my_database   # required by init_database_from_config
  timeout: 10000    # optional, default 10000

llm:
  provider: gemini
  api_key: xxx
  endpoint: https://api.example.com
  api_version: v1beta  # optional, default v1beta

s3_sources:                        # optional, for blob:// multi-source
- source_id: my-images
  endpoint: https://s3.example.com
  bucket: actual-bucket-name
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1           # optional
```

## Quick Example: Config-driven Initialization

```python
from pathlib import Path

from fyuneru.config import (
    parse_mongo_config,
    parse_redis_config,
    parse_s3_config,
    read_config,
    read_config_with_override,
)
from fyuneru.gemini_toolkit import init_client_from_config as init_llm_client
from fyuneru.mongo_toolkit import init_client_from_config as init_mongo_client
from fyuneru.mongo_toolkit import init_database_from_config
from fyuneru.redis_toolkit import init_client_from_config as init_redis_client
from fyuneru.s3_toolkit import init_client_from_config as init_s3_client
from fyuneru.s3_toolkit import init_workspace_from_config

cfg = read_config(Path("config.yml"))
cfg_with_pod = read_config_with_override(
    base=Path("config.yml"),
    override=Path("pod.yml"),
)

# Typed parsers: explicit field validation and stable value types
redis_cfg = parse_redis_config(cfg_with_pod)
s3_cfg = parse_s3_config(cfg_with_pod)
mongo_cfg = parse_mongo_config(cfg_with_pod)

# Low-level: each returns a Callable that creates the raw client
redis = init_redis_client(cfg_with_pod)()
s3_client = init_s3_client(cfg_with_pod)()
mongo_client = init_mongo_client(cfg_with_pod)()
llm = init_llm_client(cfg_with_pod)()

# High-level: returns workspace objects bound to bucket/db from config
s3_writer, s3_reader, s3_deleter = init_workspace_from_config(cfg_with_pod)()
db = init_database_from_config(cfg_with_pod)()
```
