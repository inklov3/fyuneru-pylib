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
| `config` | TOML 配置文件读取 |
| `converter` | 数据序列化工具（pickle 互转、任意对象转 JSON） |
| `markdown_utils` | Markdown 代码块包裹清除 |
| `redis_toolkit` | Redis 客户端初始化（Standalone / Cluster）、Set 操作、检查点实现 |
| `s3_toolkit` | S3 客户端创建、对象读写删除 |
| `mongo_toolkit` | MongoDB 客户端惰性初始化 |
| `dramatiq_toolkit` | Dramatiq + Redis 分布式任务：Broker 创建、消息构造与发送 |
| `gemini_toolkit` | Google Gemini API 客户端，支持自定义端点和结构化 JSON 输出 |

## 快速上手

### 日志

```python
from fyuneru.logger import init_logger, LogLevel

init_logger(level=LogLevel.INFO, log_dir=Path("./logs"))
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
from fyuneru.dramatiq_toolkit import init_broker, new_message, send_message

broker = init_broker(redis_client, namespace="myapp:{task}")
msg = new_message(actor_name="process", queue_name="default", args=(payload,))
send_message(broker, msg)
```

## 依赖

- Python >= 3.11
- 核心：loguru, returns, tqdm
- 可选：redis, boto3, dramatiq, pymongo, google-genai, av, pillow

## TODO

代码设计与命名审视发现的问题，按优先级排列：

（本轮全部已完成）

- [x] 模块重命名：`configger` → `config`，`json_utils` → `markdown_utils`，`distask_toolkit` → `dramatiq_toolkit`，`gemini_client` → `gemini_toolkit`
- [x] 函数重命名：`create_redis_broker` → `init_broker`，`checkpoint_calculator` → `calculate_checkpoint_key`，`init_s3client` → `init_client`，`get_config` → `gen_content_config`
- [x] 删除 `get_prompt`（单行 `Path.read_text()` 包装，无复用价值）
- [x] 修复 `s3_toolkit.py` 可变默认参数，改为 `config: Config | None = None` 模式
- [x] README 模块概览表和示例代码同步更新

## License

Private
