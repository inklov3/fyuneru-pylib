# fyuneru — API Reference for Claude Code

Python utility library wrapping common infrastructure components with unified, composable functional interfaces. Uses `returns` for safe error handling and `functools.partial` for lazy initialization.

## Installation

```bash
uv add fyuneru@git+https://github.com/inklov3/fyuneru-pylib.git

# With optional dependencies
uv add "fyuneru[redis] @ git+https://github.com/inklov3/fyuneru-pylib.git"
uv add "fyuneru[s3] @ git+https://github.com/inklov3/fyuneru-pylib.git"
uv add "fyuneru[mongo] @ git+https://github.com/inklov3/fyuneru-pylib.git"
uv add "fyuneru[pipeline] @ git+https://github.com/inklov3/fyuneru-pylib.git"   # Redis + S3 + Dramatiq + MongoDB
uv add "fyuneru[media] @ git+https://github.com/inklov3/fyuneru-pylib.git"      # av + Pillow
uv add "fyuneru[gemini] @ git+https://github.com/inklov3/fyuneru-pylib.git"     # Google Gemini
```

## Key Patterns

- **`init_*`** returns a `Callable` (via `functools.partial`) that lazily creates a client when called
- **`gen_*`** returns a tuple of composable operation functions (writer, reader, deleter)
- **`@safe`** from `returns` wraps return values in `Result` type; use `.unwrap()` to extract the value
- **Checkpoint** is implemented by composing `calculate_checkpoint_key()` + `gen_redis_set()` — no dedicated abstraction

## Modules

### logger (`fyuneru.logger`)

```python
from fyuneru.logger import init_logger, tqdm_loguru, LogLevel

# LogLevel: INFO, WARNING, ERROR, DEBUG

@safe
init_logger(level: str = LogLevel.INFO, log_dir: Path | None = None) -> None
# Configures loguru logger with console output + optional file output.
# When log_dir is set, creates timestamped log file and latest.log.

tqdm_loguru(iterable, level="INFO", **tqdm_kwargs) -> tqdm
# tqdm wrapper that outputs progress via loguru instead of stderr.
```

### config (`fyuneru.config`)

```python
from fyuneru.config import (
    read_config, init_redis_from_config, init_s3_from_config,
    init_mongo_from_config, init_llm_from_config,
    init_s3_workspace_from_config, init_mongo_database_from_config,
    read_config_with_override,
)

read_config(config: Path) -> dict[str, list | dict]
# Reads YAML config file (.yaml/.yml only). Empty file returns {}.
# Raises ValueError for unsupported formats or non-mapping root.

read_config_with_override(base: Path, override: Path | None = None) -> dict[str, Any]
# Reads base config and optionally overlays one override YAML.
# Merge rules:
# - dict: recursive merge, override value wins on key conflict
# - scalar: override replaces base
# - list: append (base + override)
# Non-goals: no template rendering, no field deletion semantics.

init_redis_from_config(config: dict) -> Callable
# Reads config["redis"]. Supports standalone (default) and cluster mode.
# Optional "password" field is forwarded to the Redis client.
# Raises KeyError if "redis" section missing.

init_s3_from_config(config: dict) -> Callable
# Reads config["s3"]. Returns Callable[[], S3Client].
# Raises KeyError if "s3" section missing.

init_mongo_from_config(config: dict) -> Callable
# Reads config["mongo"]. Returns Callable[[], MongoClient].
# Raises KeyError if "mongo" section missing.

init_llm_from_config(config: dict) -> Callable
# Reads config["llm"]. Currently only supports provider="gemini".
# Raises KeyError if "llm" section missing, ValueError for unsupported provider.

init_s3_workspace_from_config(config: dict) -> Callable
# Reads config["s3"] including required "bucket" field.
# Returns Callable[[], tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]].

init_mongo_database_from_config(config: dict) -> Callable
# Reads config["mongo"] including required "db" field.
# Returns Callable[[], Database].
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
    init_client_standalone, init_client_cluster,
    gen_redis_set, calculate_checkpoint_key,
)

init_client_standalone(host: str, port: int, db: int, **kwargs) -> Callable[[], Redis]
init_client_cluster(host: str, port: int, **kwargs) -> Callable[[], RedisCluster]

gen_redis_set(client: Redis | RedisCluster, set_name: str)
    -> tuple[RedisSetWriter, RedisSetReader, RedisSetDeleter]
# Returns (writer, reader, deleter) for Redis Set operations.
# writer(key: str) -> ResultE[None]   — sadd
# reader(key: str) -> ResultE[bool]   — sismember
# deleter(key: str) -> ResultE[None]  — srem

calculate_checkpoint_key(checkpoint: str, task: str, worker: str) -> str
# Returns "{worker}:{task}:checkpoint:{checkpoint}"
```

**Checkpoint pattern:**
```python
checkpoint_key = calculate_checkpoint_key(checkpoint="step1", task="etl", worker="w1")
advance, is_past, delete = gen_redis_set(redis, set_name=checkpoint_key)
advance("item-001").unwrap()
assert is_past("item-001").unwrap() is True
```

### s3_toolkit (`fyuneru.s3_toolkit`)

Requires: `fyuneru[s3]`

```python
from fyuneru.s3_toolkit import (
    init_client, gen_s3writer, gen_s3reader, gen_s3deleter, gen_s3lister,
)

init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config: Config | None = None,    # botocore.config.Config
) -> Callable[[], S3Client]
# Default config: signature_version="s3v4", addressing_style="virtual"

gen_s3writer(client: S3Client, bucket: str) -> ObjectStorageWriter
# writer(key: str, body: bytes) -> ResultE[None]  — put_object

gen_s3reader(client: S3Client, bucket: str) -> ObjectStorageReader
# reader(key: str) -> ResultE[bytes]               — get_object

gen_s3deleter(client: S3Client, bucket: str) -> ObjectStorageDeleter
# deleter(key: str) -> ResultE[None]               — delete_object

gen_s3lister(client: S3Client, bucket: str) -> ObjectStorageLister
# lister(prefix: str, suffix: str | None = None) -> ResultE[list[str]]
# Auto-paginates via list_objects_v2 + ContinuationToken.
# Filters out directory placeholders (keys ending with "/").
# Optional suffix filter applied client-side.
```

### s3_source (`fyuneru.s3_source`)

Requires: `fyuneru[s3]`

通过 `blob://桶id/key` URI 协议透明访问多个 S3 源。

```python
from fyuneru.s3_source import parse_blob_uri, load_source_registry, init_source_reader

parse_blob_uri(uri: str) -> tuple[str, str]
# Parses "blob://bucket_id/key" -> (bucket_id, key).
# Raises ValueError for invalid format.

load_source_registry(
    config: dict,
) -> dict[str, dict]
# Reads config["s3_sources"] list, converts to dict keyed by source_id.
# When duplicate source_id is found, logs warning and uses later entry to override earlier.

init_source_reader(registry: dict[str, dict]) -> Callable[[str], ResultE[bytes]]
# Returns a closure that reads from blob:// URIs.
# Lazily initializes S3 clients per bucket_id, caches them.
```

**Usage:**
```python
from fyuneru.config import read_config_with_override
from fyuneru.s3_source import load_source_registry, init_source_reader

config = read_config_with_override(Path("config.yml"))
registry = load_source_registry(config)
read = init_source_reader(registry)
data = read("blob://my-images/photos/img001.jpg").unwrap()
```

**Overlay note:**
- For `s3_sources`, merge behavior is append + dedupe by `source_id` (later item wins).

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
from fyuneru.mongo_toolkit import init_client

init_client(uri: str, timeout: int = 10000)
    -> Callable[[], MongoClient]
# timeout is serverSelectionTimeoutMS
# Always returns a MongoClient initializer.
```

### dramatiq_toolkit (`fyuneru.dramatiq_toolkit`)

Requires: `fyuneru[pipeline]`

```python
from fyuneru.dramatiq_toolkit import (
    calculate_namespace, init_broker, new_message, send_message,
)

calculate_namespace(worker: str, task: str) -> str
# Returns "{worker}:{{{task}}}"

init_broker(redis_client: Redis | RedisCluster, namespace: str) -> Broker
# Creates a Dramatiq RedisBroker. For RedisCluster, sets dramatiq_lua_max_stack=8000.

new_message(
    actor_name: str,
    queue_name: str,
    args: tuple = (),
    kwargs: dict[str, Any] | None = None,
    options: dict | None = None,
) -> Message

send_message(broker: Broker, message: Message) -> Message
# Enqueues message on the broker.
```

### gemini_toolkit (`fyuneru.gemini_toolkit`)

Requires: `fyuneru[gemini]`

```python
from fyuneru.gemini_toolkit import init_client, gen_content_config

init_client(api_key: str, endpoint: str, api_version: str = "v1beta")
    -> Callable[[], Client]
# Creates a google.genai.Client with custom endpoint and auth headers.

gen_content_config(
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
    config=gen_content_config(
        schema=MyModel.model_json_schema(),
        system_instruction=system_prompt,
    ),
)
result = MyModel.model_validate_json(response.text)
```

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

mongo:
  uri: mongodb://localhost:27017
  db: my_database   # required by init_mongo_database_from_config
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
    read_config, init_redis_from_config, init_s3_from_config,
    init_mongo_from_config, init_llm_from_config,
    init_s3_workspace_from_config, init_mongo_database_from_config,
    read_config_with_override,
)

cfg = read_config(Path("config.yml"))
cfg_with_pod = read_config_with_override(
    base=Path("config.yml"),
    override=Path("pod.yml"),
)

# Low-level: each returns a Callable that creates the raw client
redis = init_redis_from_config(cfg_with_pod)()
s3_client = init_s3_from_config(cfg_with_pod)()
mongo_client = init_mongo_from_config(cfg_with_pod)()
llm = init_llm_from_config(cfg_with_pod)()

# High-level: returns workspace objects bound to bucket/db from config
s3_writer, s3_reader, s3_deleter = init_s3_workspace_from_config(cfg_with_pod)()
db = init_mongo_database_from_config(cfg_with_pod)()
```
