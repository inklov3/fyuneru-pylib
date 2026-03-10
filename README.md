# fyuneru

> Python 工具库，封装常用基础设施组件，提供统一、可组合的函数式接口。

## 命名规范

- `init` — 惰性创建句柄（返回 `Callable`，延迟实例化）
- `gen` — 展开/生成函数

## 安装

> **注意**：PyPI 上的版本可能不是最新的，建议从 GitHub 源安装以获取最新功能。

推荐使用 [uv](https://docs.astral.sh/uv/) 管理依赖：

```bash
# 从 GitHub 安装最新版本
uv add fyuneru@git+https://github.com/znklov3/fyuneru.git
```

按需安装可选依赖：

```bash
uv add "fyuneru[redis] @ git+https://github.com/znklov3/fyuneru.git"      # Redis 支持
uv add "fyuneru[s3] @ git+https://github.com/znklov3/fyuneru.git"         # S3 对象存储支持
uv add "fyuneru[mongo] @ git+https://github.com/znklov3/fyuneru.git"      # MongoDB 支持
uv add "fyuneru[pipeline] @ git+https://github.com/znklov3/fyuneru.git"   # 分布式任务流水线 (Redis + S3 + Dramatiq + MongoDB)
uv add "fyuneru[media] @ git+https://github.com/znklov3/fyuneru.git"      # 媒体处理 (av + Pillow)
uv add "fyuneru[gemini] @ git+https://github.com/znklov3/fyuneru.git"     # Google Gemini 客户端
```

## 模块概览

| 模块 | 说明 |
|------|------|
| `logger` | 基于 loguru 的日志模块，支持文件输出和 tqdm 进度条集成 |
| `config` | YAML 配置读取 + 纯函数式 client 初始化（Redis / S3 / MongoDB / LLM） |
| `converter` | 数据序列化工具（pickle 字节互转、任意对象转 JSON） |
| `markdown_utils` | Markdown 代码块包裹清除 |
| `redis_toolkit` | Redis 客户端初始化（Standalone / Cluster）、Set 操作、检查点 key 计算 |
| `s3_toolkit` | S3 客户端创建、对象读写删除 |
| `s3_source` | S3 多源协议（`blob://桶id/key`），透明读取多个 S3 源 |
| `mongo_toolkit` | MongoDB 客户端惰性初始化 |
| `dramatiq_toolkit` | Dramatiq + Redis 分布式任务：Broker 创建、命名空间计算、消息构造与发送 |
| `gemini_toolkit` | Google Gemini API 客户端，支持自定义端点和结构化 JSON 输出 |

## 快速上手

### 日志

```python
from fyuneru.logger import init_logger, tqdm_loguru, LogLevel

# 初始化日志，可选输出到文件
init_logger(level=LogLevel.INFO, log_dir=Path("./logs"))

# 用 loguru 输出 tqdm 进度条
for item in tqdm_loguru(items, desc="Processing"):
    process(item)
```

### 配置

```python
from pathlib import Path
from fyuneru.config import read_config

# 仅支持 YAML（.yaml / .yml），传入 .toml 等其他格式会抛出 ValueError
cfg = read_config(Path("config.yml"))
```

### 从配置文件初始化各 client

```python
from pathlib import Path
from fyuneru.config import (
    read_config,
    init_redis_from_config,
    init_s3_from_config,
    init_mongo_from_config,
    init_llm_from_config,
    init_s3_workspace_from_config,
    init_mongo_database_from_config,
)

cfg = read_config(Path("config.yml"))

# 底层：各函数返回 Callable，调用后才真正创建连接
# 配置段不存在时抛出 KeyError
redis_getter = init_redis_from_config(cfg)   # 支持 standalone / cluster
s3_getter = init_s3_from_config(cfg)         # 返回 S3Client
mongo_getter = init_mongo_from_config(cfg)   # 返回 MongoClient
llm_getter = init_llm_from_config(cfg)       # 目前支持 gemini

redis = redis_getter()
s3_client = s3_getter()
mongo_client = mongo_getter()
llm = llm_getter()

# 高层：绑定配置中的 bucket/db，返回可直接使用的对象工厂
s3_writer, s3_reader, s3_deleter = init_s3_workspace_from_config(cfg)()
db = init_mongo_database_from_config(cfg)()
```

YAML 配置结构参考 [`example.yml`](example.yml)。

### 数据转换

```python
from fyuneru.converter import object_to_bytes, bytes_to_object, to_json_object

# pickle 序列化/反序列化
raw = object_to_bytes({"key": "value"})
obj = bytes_to_object(raw)

# 任意对象转 JSON 兼容结构
json_obj = to_json_object(some_object)
```

### Markdown 工具

```python
from fyuneru.markdown_utils import unwrap_codeblock

code = unwrap_codeblock("```python\nprint('hello')\n```")
# => "print('hello')\n"
```

### Gemini 客户端

```python
from fyuneru.gemini_toolkit import init_client, gen_content_config

gemini_getter = init_client(api_key="sk_xxxx", endpoint="https://xxx")
client = gemini_getter()

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

### S3 对象存储

```python
from fyuneru.s3_toolkit import init_client, gen_s3worker

client = init_client(endpoint="https://s3.example.com", access_key_id="ak", secret_access_key="sk")
write, read, delete = gen_s3worker(client(), bucket="my-bucket")

write("key", b"data").unwrap()
data = read("key").unwrap()
```

### S3 多源读取

通过 `blob://桶id/key` URI 协议透明访问多个 S3 源。配置格式参考 [`example.yml`](example.yml) 中的 `s3_sources` 段。

```python
from pathlib import Path
from fyuneru.s3_source import load_source_registry, init_source_reader

registry = load_source_registry(Path("config.yml"))
read = init_source_reader(registry)

result = read("blob://my-images/photos/2024/img001.jpg")
# result: Result[bytes, Exception]
data = result.unwrap()
```

### Redis

```python
from fyuneru.redis_toolkit import init_client_standalone, gen_redis_set, calculate_checkpoint_key

redis_getter = init_client_standalone(host="localhost", port=6379, db=0)
redis = redis_getter()

# Set 操作
add, contains, remove = gen_redis_set(redis, set_name="my_set")
add("item-001").unwrap()
assert contains("item-001").unwrap() is True

# 检查点（基于 Redis Set 实现）
checkpoint_key = calculate_checkpoint_key(checkpoint="step1", task="etl", worker="w1")
advance, is_past, delete = gen_redis_set(redis, set_name=checkpoint_key)
advance("item-001").unwrap()
assert is_past("item-001").unwrap() is True
```

### MongoDB

```python
from fyuneru.mongo_toolkit import init_client

# 不指定 db：返回 MongoClient
mongo_getter = init_client(uri="mongodb://localhost:27017")
client = mongo_getter()
db = client["my_database"]

# 指定 db：调用后直接返回 Database
db_getter = init_client(uri="mongodb://localhost:27017", db="my_database")
db = db_getter()
```

### 分布式任务

```python
from fyuneru.dramatiq_toolkit import init_broker, new_message, send_message, calculate_namespace

namespace = calculate_namespace(worker="w1", task="etl")
broker = init_broker(redis_client, namespace=namespace)
msg = new_message(actor_name="process", queue_name="default", args=(payload,))
send_message(broker, msg)
```

## 依赖

- Python >= 3.11
- 核心：loguru, returns, tqdm
- 可选：redis, boto3, dramatiq, pymongo, google-genai, av, pillow

## License

Private
