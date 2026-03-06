# fyuneru — API Reference for Claude Code

Python utility library wrapping common infrastructure components with unified, composable functional interfaces. Uses `returns` for safe error handling and `functools.partial` for lazy initialization.

## Installation

```bash
uv add fyuneru@git+https://github.com/znklov3/fyuneru.git

# With optional dependencies
uv add "fyuneru[redis] @ git+https://github.com/znklov3/fyuneru.git"
uv add "fyuneru[s3] @ git+https://github.com/znklov3/fyuneru.git"
uv add "fyuneru[mongo] @ git+https://github.com/znklov3/fyuneru.git"
uv add "fyuneru[pipeline] @ git+https://github.com/znklov3/fyuneru.git"   # Redis + S3 + Dramatiq + MongoDB
uv add "fyuneru[media] @ git+https://github.com/znklov3/fyuneru.git"      # av + Pillow
uv add "fyuneru[gemini] @ git+https://github.com/znklov3/fyuneru.git"     # Google Gemini
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
)

read_config(config: Path) -> dict[str, list | dict]
# Reads YAML config file (.yaml/.yml only). Raises ValueError for other formats.

init_redis_from_config(config: dict) -> Callable
# Reads config["redis"]. Supports standalone (default) and cluster mode.
# Raises KeyError if "redis" section missing.

init_s3_from_config(config: dict) -> Callable
# Reads config["s3"]. Raises KeyError if "s3" section missing.

init_mongo_from_config(config: dict) -> Callable
# Reads config["mongo"]. Raises KeyError if "mongo" section missing.

init_llm_from_config(config: dict) -> Callable
# Reads config["llm"]. Currently only supports provider="gemini".
# Raises KeyError if "llm" section missing, ValueError for unsupported provider.
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
# writer(key: str) -> Result[None, Exception]   — sadd
# reader(key: str) -> Result[bool, Exception]   — sismember
# deleter(key: str) -> Result[None, Exception]  — srem

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
from fyuneru.s3_toolkit import init_client, gen_s3worker

init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config: Config | None = None,    # botocore.config.Config
) -> Callable[[], S3Client]
# Default config: signature_version="s3v4", addressing_style="virtual"

gen_s3worker(client: S3Client, bucket: str)
    -> tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]
# writer(key: str, body: bytes) -> Result[None, Exception]  — put_object
# reader(key: str) -> Result[bytes, Exception]               — get_object
# deleter(key: str) -> Result[None, Exception]               — delete_object
```

### mongo_toolkit (`fyuneru.mongo_toolkit`)

Requires: `fyuneru[mongo]`

```python
from fyuneru.mongo_toolkit import init_client

init_client(uri: str, timeout: int = 10000) -> Callable[[], MongoClient]
# timeout is serverSelectionTimeoutMS
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

s3:
  endpoint: https://s3.example.com
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1  # optional

mongo:
  uri: mongodb://localhost:27017
  timeout: 10000    # optional, default 10000

llm:
  provider: gemini
  api_key: xxx
  endpoint: https://api.example.com
  api_version: v1beta  # optional, default v1beta
```

## Quick Example: Config-driven Initialization

```python
from pathlib import Path
from fyuneru.config import (
    read_config, init_redis_from_config, init_s3_from_config,
    init_mongo_from_config, init_llm_from_config,
)

cfg = read_config(Path("config.yml"))

# Each returns a Callable; call it to create the actual connection
redis = init_redis_from_config(cfg)()
s3 = init_s3_from_config(cfg)()
mongo = init_mongo_from_config(cfg)()
llm = init_llm_from_config(cfg)()
```
