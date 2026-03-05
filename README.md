# fyuneru

> Python 工具库，封装常用基础设施组件，提供统一、可组合的函数式接口。

## 命名规范

- `init` — 惰性创建句柄（返回 `Callable`，延迟实例化）
- `gen` — 展开/生成函数

## 安装

```bash
pip install fyuneru
```

按需安装可选依赖：

```bash
pip install fyuneru[redis]      # Redis 支持
pip install fyuneru[s3]         # S3 对象存储支持
pip install fyuneru[pipeline]   # 分布式任务流水线 (Redis + S3 + Dramatiq + MongoDB)
pip install fyuneru[media]      # 媒体处理 (av + Pillow)
pip install fyuneru[gemini]     # Google Gemini 客户端
```

## 模块概览

| 模块 | 说明 |
|------|------|
| `logger` | 基于 loguru 的日志模块，支持文件输出和 tqdm 进度条集成 |
| `configger` | TOML 配置文件读取 |
| `converter` | 数据序列化工具（pickle 互转、任意对象转 JSON） |
| `json_utils` | Markdown 代码块包裹清除 |
| `redis_toolkit` | Redis 客户端初始化（Standalone / Cluster）、Set 操作、检查点实现 |
| `s3_toolkit` | S3 客户端创建、对象读写删除 |
| `mongo_toolkit` | MongoDB 客户端惰性初始化 |
| `distask_toolkit` | Dramatiq + Redis 分布式任务：Broker 创建、消息构造与发送、RedisCluster Lua 兼容层 |
| `gemini_client` | Google Gemini API 客户端，支持自定义端点和结构化 JSON 输出 |

## 快速上手

### 日志

```python
from fyuneru.logger import init_logger, LogLevel

init_logger(level=LogLevel.INFO, log_dir=Path("./logs"))
```

### Gemini 客户端

```python
from fyuneru.gemini_client import init_client, get_config

gemini_getter = init_client(api_key="sk_xxxx", endpoint="https://xxx")
client = gemini_getter()

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[prompt],
    config=get_config(
        schema=MyModel.model_json_schema(),
        system_instruction=system_prompt,
    ),
)
result = MyModel.model_validate_json(response.text)
```

### S3 对象存储

```python
from fyuneru.s3_toolkit import init_s3client, gen_s3worker

client = init_s3client(endpoint="https://s3.example.com", access_key_id="ak", secret_access_key="sk")
write, read, delete = gen_s3worker(client(), bucket="my-bucket")

write("key", b"data").unwrap()
data = read("key").unwrap()
```

### Redis 检查点

```python
from fyuneru.redis_toolkit import init_client_standalone, gen_checkpointer

redis_getter = init_client_standalone(host="localhost", port=6379, db=0)
redis = redis_getter()

advance, is_past, delete = gen_checkpointer(redis, checkpoint="step1", task="etl", worker="w1")
advance("item-001").unwrap()
assert is_past("item-001").unwrap() is True
```

### 分布式任务

```python
from fyuneru.distask_toolkit import create_redis_broker, new_message, send_message

broker = create_redis_broker(redis_client, namespace="myapp:{task}")
msg = new_message(actor_name="process", queue_name="default", args=(payload,))
send_message(broker, msg)
```

## 依赖

- Python >= 3.11
- 核心：loguru, returns, tqdm
- 可选：redis, boto3, dramatiq, pymongo, google-genai, av, pillow

## TODO

代码复核发现的问题，按优先级排列：

### P0 — 运行时错误

- [x] **`redis_toolkit.py:9-13`** — 导入已删除的 `fyuneru.checkpointer` 模块（`AdvanceCheckpoint`, `DelCheckpoint`, `IsPastCheckpoint`），运行时必定 `ImportError`。将 Protocol 定义内联到 `redis_toolkit.py`，或删除这些类型引用。
- [x] **`pyproject.toml:13-18` 与 `54-57`** — `[dependency-groups] dev` 重复定义，TOML 规范不允许同级重复 key，后者会覆盖前者或导致解析错误。合并为一个 `[dependency-groups] dev`。

### P1 — 经典缺陷

- [x] **`distask_toolkit.py:28-29`** — `kwargs: dict = {}`, `options: dict = {}` 使用可变默认参数，多次调用共享同一对象。改为 `None`，函数体内 `kwargs = kwargs or {}`。

### P2 — 命名 / 文档错误

- [x] **`json_utils.py:4`** — 函数名拼写错误 `unwrap_codeblack`，应为 `unwrap_codeblock`。
- [x] **`logger.py:50-53`** — docstring 写在 `from loguru import logger` 之后，不会被识别为函数文档。应移到函数签名正下方。
- [x] **`gemini_client.py:16`** — docstring 写 `endpoint: 默认为 None 使用官方端点`，但参数实际是必填 (`str`)，无默认值。

### P3 — 代码风格

- [x] **`s3_toolkit.py:55`** — `client: S3Client = client` 无意义的自赋值。
- [x] **`redis_toolkit.py:54`** — `set_name = set_name` 无意义的自赋值。
- [x] **`logger.py:26`** — 变量名 `format` 遮蔽内置函数 `format()`。

## License

Private
