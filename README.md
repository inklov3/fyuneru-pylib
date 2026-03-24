# fyuneru

> Python 工具库，按统一的函数式约定封装常用基础设施组件。核心模式是：`init_*` 做惰性初始化，`gen_*` 生成可组合操作函数，错误通过 `returns.Result` 显式返回。

## 项目定位

`fyuneru` 用来把 Redis、S3、MongoDB、Dramatiq、Gemini 等基础设施访问整理成更小、更稳定的组合单元。

- 推荐从子模块导入，例如 `from fyuneru.redis_toolkit import gen_redis_set`
- 默认安装只包含核心依赖；使用 Redis、MongoDB、Gemini 等能力时，需要安装对应 extra
- `config.py` 只读取 YAML，并支持 `base.yml + pod.yml` 的单层增量覆盖；调用 `init_*_from_config` 时延迟导入对应 toolkit，避免默认安装下导入 `fyuneru.config` 就因为缺少可选依赖失败

## 核心约定

- `init_*`：返回 `Callable`，调用时才真正创建 client 或 handle
- `gen_*`：返回一组可直接组合的操作函数
- `@safe`：把可能失败的操作包装成 `ResultE[...]`；需要值时再 `.unwrap()`
- 顶层 `fyuneru` 不提供统一 re-export，建议直接从具体子模块导入

## 安装

要求：Python `>= 3.11`

以下示例默认使用 GitHub 源安装：

```bash
uv add fyuneru@git+https://github.com/inklov3/fyuneru-pylib.git
```

按需启用可选依赖：

| 安装方式 | 对应能力 | 主要模块 |
| --- | --- | --- |
| 默认安装 | 日志、YAML 配置、pickle/JSON 转换、Markdown 工具 | `logger`、`config`、`converter`、`markdown_utils` |
| `fyuneru[redis]` | Redis client、Set 封装、checkpoint key 计算 | `redis_toolkit`、`config.init_redis_from_config` |
| `fyuneru[s3]` | S3 client、对象读写删除列举、多源 `blob://` 读取 | `s3_toolkit`、`s3_source`、`config.init_s3_from_config`、`config.init_s3_workspace_from_config` |
| `fyuneru[mongo]` | MongoClient 惰性初始化与按配置获取 `Database` | `mongo_toolkit`、`config.init_mongo_from_config`、`config.init_mongo_database_from_config` |
| `fyuneru[gemini]` | Google Gemini client 与结构化 JSON 输出配置 | `gemini_toolkit`、`config.init_llm_from_config` |
| `fyuneru[pipeline]` | Redis + S3 + Dramatiq + MongoDB 的组合依赖 | `dramatiq_toolkit` 及 `redis` / `s3` / `mongo` 相关模块 |
| `fyuneru[media]` | 安装 `av` / `Pillow` 依赖，便于上层媒体处理代码复用 | 当前仓库未提供独立 `media` toolkit |

例如：

```bash
uv add "fyuneru[redis,s3] @ git+https://github.com/inklov3/fyuneru-pylib.git"
```

任何依赖可选第三方包的模块都应先安装对应 extra，例如 `fyuneru.redis_toolkit`、`fyuneru.s3_toolkit`、`fyuneru.mongo_toolkit`、`fyuneru.dramatiq_toolkit`、`fyuneru.gemini_toolkit`。

## 模块概览

| 模块 | 说明 | 安装要求 |
| --- | --- | --- |
| `fyuneru.logger` | 基于 loguru 的日志初始化与 tqdm 集成 | 默认安装 |
| `fyuneru.config` | YAML 配置读取（含单层增量覆盖），以及按配置构建各类 initializer | 默认安装；调用具体 helper 时需要对应 extra |
| `fyuneru.converter` | pickle 字节互转、任意对象转 JSON 兼容结构 | 默认安装 |
| `fyuneru.markdown_utils` | 去掉 Markdown 代码块包裹，保留正文 | 默认安装 |
| `fyuneru.redis_toolkit` | Redis / RedisCluster 惰性初始化、Set 操作、checkpoint key 计算 | `redis` |
| `fyuneru.s3_toolkit` | S3 client 初始化与对象读写删除列举 | `s3` |
| `fyuneru.s3_source` | 通过 `blob://桶id/key` 协议透明读取多个 S3 源 | `s3` |
| `fyuneru.mongo_toolkit` | MongoClient 惰性初始化 | `mongo` |
| `fyuneru.dramatiq_toolkit` | Dramatiq broker 初始化、消息构造与投递 | `pipeline` |
| `fyuneru.gemini_toolkit` | Gemini client 初始化与结构化输出配置 | `gemini` |

## 快速上手

### 日志

```python
from pathlib import Path

from fyuneru.logger import LogLevel, init_logger, tqdm_loguru

init_logger(level=LogLevel.INFO, log_dir=Path("./logs")).unwrap()

for item in tqdm_loguru(items, desc="Processing"):
    process(item)
```

### YAML 配置与按配置初始化

`read_config` / `read_config_with_override` 只支持 `.yaml` / `.yml`。完整配置结构见 [`example.yml`](example.yml)。

```python
from pathlib import Path

from fyuneru.config import (
    init_llm_from_config,
    init_mongo_database_from_config,
    init_mongo_from_config,
    init_redis_from_config,
    init_s3_from_config,
    init_s3_workspace_from_config,
    read_config,
    read_config_with_override,
)

cfg = read_config(Path("config.yml"))
cfg_with_pod = read_config_with_override(
    Path("config.yml"),
    Path("pod.yml"),
)

# 底层 helper：返回裸 client 工厂
redis_getter = init_redis_from_config(cfg_with_pod)
s3_getter = init_s3_from_config(cfg_with_pod)
mongo_getter = init_mongo_from_config(cfg_with_pod)
llm_getter = init_llm_from_config(cfg_with_pod)

redis = redis_getter()
s3_client = s3_getter()
mongo_client = mongo_getter()
llm = llm_getter()

# 高层 helper：直接绑定配置中的 bucket / db
write, read, delete = init_s3_workspace_from_config(cfg_with_pod)()
db = init_mongo_database_from_config(cfg_with_pod)()
```

### Pod YAML 增量覆盖规则

`read_config_with_override(base, override)` 使用以下规则：

- `dict`：递归合并，同名键由 override 覆盖
- 标量：override 直接替换 base
- `list`：默认追加（`base + override`）
- 特例 `s3_sources`：按 `source_id` 去重，重复时后者覆盖前者（override 生效）

当前不支持模板变量渲染、字段删除语义（例如用 `null` 删除 base 字段）。

### Redis：Set 与 checkpoint

```python
from fyuneru.redis_toolkit import (
    calculate_checkpoint_key,
    gen_redis_set,
    init_client_standalone,
)

redis = init_client_standalone(
    host="localhost",
    port=6379,
    db=0,
    password="secret",
)()

checkpoint_key = calculate_checkpoint_key(
    checkpoint="step1",
    task="etl",
    worker="worker-a",
)
write_set, read_set, delete_set = gen_redis_set(redis, set_name=checkpoint_key)

write_set("item-001").unwrap()
assert read_set("item-001").unwrap() is True
delete_set("item-001").unwrap()
```

### S3 对象存储

```python
from fyuneru.s3_toolkit import (
    gen_s3deleter,
    gen_s3lister,
    gen_s3reader,
    gen_s3writer,
    init_client,
)

client = init_client(
    endpoint="https://s3.example.com",
    access_key_id="ak",
    secret_access_key="sk",
    region_name="us-east-1",
)()

write = gen_s3writer(client, bucket="my-bucket")
read = gen_s3reader(client, bucket="my-bucket")
delete = gen_s3deleter(client, bucket="my-bucket")
lister = gen_s3lister(client, bucket="my-bucket")

write("demo.txt", b"hello").unwrap()
data = read("demo.txt").unwrap()
keys = lister(prefix="data/", suffix=".parquet").unwrap()
delete("demo.txt").unwrap()
```

### S3 多源读取

通过 `blob://桶id/key` URI 透明访问多个 S3 源。协议和配置说明见 [`docs/s3_source_protocol.md`](docs/s3_source_protocol.md)。

```python
from pathlib import Path

from fyuneru.s3_source import init_source_reader, load_source_registry

# 无覆盖层
registry = load_source_registry(Path("config.yml"))

# 带 Pod 覆盖层
registry = load_source_registry(
    config_path=Path("config.yml"),
    override_path=Path("pod.yml"),
)
read = init_source_reader(registry)

data = read("blob://my-images/photos/2024/img001.jpg").unwrap()
```

### MongoDB

`mongo_toolkit.init_client(uri, timeout)` 只返回 `MongoClient` 工厂；如果你想直接拿到 `Database`，应通过 `config.init_mongo_database_from_config`。

```python
from fyuneru.mongo_toolkit import init_client

client = init_client(uri="mongodb://localhost:27017")()
db = client["my_database"]
collection = db["items"]
```

### 分布式任务

```python
from fyuneru.dramatiq_toolkit import (
    calculate_namespace,
    init_broker,
    new_message,
    send_message,
)

namespace = calculate_namespace(worker="worker-a", task="etl")
broker = init_broker(redis_client, namespace=namespace)
message = new_message(
    actor_name="process_item",
    queue_name="default",
    args=("payload",),
)
send_message(broker, message)
```

### Gemini 结构化输出

```python
from fyuneru.gemini_toolkit import gen_content_config, init_client

client = init_client(
    api_key="sk_xxxx",
    endpoint="https://api.example.com",
)()

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

### 基础转换工具

```python
from fyuneru.converter import bytes_to_object, object_to_bytes, to_json_object
from fyuneru.markdown_utils import unwrap_codeblock

payload = {"key": "value"}
raw = object_to_bytes(payload)
restored = bytes_to_object(raw)
json_obj = to_json_object(payload)

code = unwrap_codeblock("```python\nprint('hello')\n```")
```

## 开发

安装开发依赖：

```bash
uv sync --group dev
```

如果需要验证可选模块，补上对应 extra：

```bash
uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media
```

发布前检查：

```bash
./pre_release.sh
```

脚本会先同步完整开发/可选依赖，再顺序执行：

```bash
uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media
uv run ruff check src/
uv run pyrefly check src/
uv run python test/test_s3_source.py
uv run python test/test_logger.py
uv run python test/test_config.py
```

当前仓库测试通过脚本执行，不是 pytest 工作流。

包源码位于 `src/fyuneru/`。

## 相关文件

- 配置示例：[`example.yml`](example.yml)
- 协议文档：[`docs/s3_source_protocol.md`](docs/s3_source_protocol.md)
- 变更记录：[`CHANGELOG.md`](CHANGELOG.md)

## License

Private
