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
- **Checkpoint** is implemented by composing `calculate_checkpoint_key()` + redis set binders — no dedicated abstraction

## Modules

### logger (`fyuneru.logger`)

```python
from fyuneru.logger import configure_logger, tqdm_loguru, LogLevel

# LogLevel: INFO, WARNING, ERROR, DEBUG

configure_logger(level: str = LogLevel.INFO, log_dir: Path | None = None) -> ResultE[None]
# Decorated with @safe; call unwrap(result) to raise on failure.
# Configures loguru logger with console output + optional file output.
# When log_dir is set, creates timestamped log file and latest.log.

tqdm_loguru(iterable, level="INFO", **tqdm_kwargs) -> tqdm
# tqdm wrapper that outputs progress via loguru instead of stderr.
```

### config (`fyuneru.config`)

```python
from fyuneru.config import read_config, read_config_with_override

read_config(config: Path) -> dict[str, list | dict]
# Reads YAML config file. Empty file returns {}.
# Raises ValueError for non-mapping root.

read_config_with_override(base: Path, override: Path | None = None) -> dict[str, Any]
# Reads base config and optionally overlays one override YAML.
# Merge rules:
# - dict: recursive merge, override value wins on key conflict
# - scalar: override replaces base
# - list: append (base + override)
# Non-goals: no template rendering, no field deletion semantics.
```

### converter (`fyuneru.converter`)

```python
from fyuneru.converter import object_to_bytes, bytes_to_object, to_json_object, NonSerializable

object_to_bytes(data: Any) -> bytes        # pickle serialize
bytes_to_object(data: bytes) -> Any        # pickle deserialize

to_json_object(data: Any) -> Any
# Recursively converts any object to JSON-compatible structure.
# Handles: primitives, namedtuples, list/tuple/set, dict, objects with __dict__.
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

calculate_checkpoint_key(checkpoint: str, task: str, worker: str) -> str
# Returns "{worker}:{task}:checkpoint:{checkpoint}"
```

**Checkpoint pattern:**
```python
from fyuneru.result import unwrap

checkpoint_key = calculate_checkpoint_key(checkpoint="step1", task="etl", worker="w1")
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
    bind_s3_deleter,
    bind_s3_lister,
    bind_s3_reader,
    bind_s3_writer,
    init_client,
)

init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config: Config | None = None,    # botocore.config.Config
) -> Callable[[], S3Client]
# Default config: signature_version="s3v4", addressing_style="virtual"

init_client_from_config(config: dict) -> Callable[[], S3Client]
# Reads config["s3"]. Returns Callable[[], S3Client].
# Raises KeyError if "s3" section missing.

init_workspace_from_config(config: dict) -> Callable
# Reads config["s3"] including required "bucket" field.
# Returns Callable[[], tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]].

bind_s3_writer(client: S3Client, bucket: str) -> ObjectStorageWriter
# writer(key: str, body: bytes) -> ResultE[None]  — put_object

bind_s3_reader(client: S3Client, bucket: str) -> ObjectStorageReader
# reader(key: str) -> ResultE[bytes]               — get_object

bind_s3_deleter(client: S3Client, bucket: str) -> ObjectStorageDeleter
# deleter(key: str) -> ResultE[None]               — delete_object

bind_s3_lister(client: S3Client, bucket: str) -> ObjectStorageLister
# lister(prefix: str, suffix: str | None = None) -> ResultE[list[str]]
# Auto-paginates via list_objects_v2 + ContinuationToken.
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
from fyuneru.mongo_toolkit import init_client, init_client_from_config, init_database_from_config

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
```

### task_queue (`fyuneru.task_queue`)

Requires: `fyuneru[pipeline]`

```python
from fyuneru.task_queue import (
    actor,
    build_broker,
    calculate_namespace,
    new_message,
    send_message,
)

calculate_namespace(worker: str, task: str) -> str
# Returns "{worker}:{{{task}}}"

build_broker(
    redis_client: Redis | RedisCluster,
    namespace: str,
    group_name: str = "default",
    max_retries: int = 0,
    claim_idle_ms: int | None = None,
    xq_stream: str | None = None,
) -> TaskQueueBroker
# Builds Redis Streams based task broker.

actor(
    broker: TaskQueueBroker,
    queue_name: str = "default",
    name: str | None = None,
) -> Callable[[TaskHandler], RegisteredActor]
# Registers a handler and returns actor object with .send(payload).

new_message(
    name: str,
    queue_name: str,
    payload: Any,
    attempt: int = 0,
    eta: float | None = None,
) -> TaskMessage

send_message(broker: TaskQueueBroker, message: TaskMessage) -> ResultE[str]
# Enqueues message into stream and returns message id.

TaskQueueBroker.run_worker(
    queue_name: str = "default",
    consumer_name: str = "worker-1",
    block_ms: int = 1000,
    max_messages: int | None = None,
    stop_when_idle: bool = False,
) -> ResultE[int]
# Consumes and executes tasks; acks on success.
# On failure, retries up to max_retries then writes to XQ stream.
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
  region_name: us-east-1  # optional
  bucket: my-bucket        # required by init_workspace_from_config

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

from fyuneru.config import read_config, read_config_with_override
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

# Low-level: each returns a Callable that creates the raw client
redis = init_redis_client(cfg_with_pod)()
s3_client = init_s3_client(cfg_with_pod)()
mongo_client = init_mongo_client(cfg_with_pod)()
llm = init_llm_client(cfg_with_pod)()

# High-level: returns workspace objects bound to bucket/db from config
s3_writer, s3_reader, s3_deleter = init_workspace_from_config(cfg_with_pod)()
db = init_database_from_config(cfg_with_pod)()
```
