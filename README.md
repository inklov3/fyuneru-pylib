# fyuneru

> Python 工具库，按统一的函数式约定封装常用基础设施组件。核心模式是：`init_*` 做惰性初始化，`bind_*` 绑定资源生成可组合操作函数，`build_*` 构建组合对象，错误通过 `fyuneru.result.Result` 显式返回。

## 项目定位

`fyuneru` 用来把 Redis、S3、Redis Streams 任务队列、Gemini 等基础设施访问整理成更小、更稳定的组合单元。

- 推荐从子模块导入，例如 `from fyuneru.redis_toolkit import bind_redis_set_writer`
- 默认安装只包含核心依赖；使用 Redis、Gemini 等能力时，需要安装对应 extra
- `config.py` 只读取 YAML，并支持 `base.yml + pod.yml` 的单层增量覆盖；同时提供 `parse_redis_config` / `parse_s3_config` 强类型解析器

## 核心约定

- `init_*`：返回 `Callable`，调用时才真正创建 client 或 handle
- `bind_*`：绑定 client + 资源名，返回单一操作函数
- `build_*`：构建已绑定的组合对象
- `@safe`：把可能失败的操作包装成 `ResultE[...]`；需要值时使用 `unwrap(result)`
- 顶层 `fyuneru` 不提供统一 re-export，建议直接从具体子模块导入

## 安装

要求：Python `>= 3.14`

以下示例默认使用 GitHub 源安装：

```bash
uv add fyuneru@git+https://github.com/inklov3/fyuneru-pylib.git
```

按需启用可选依赖：

| 安装方式 | 对应能力 | 主要模块 |
| --- | --- | --- |
| 默认安装 | 日志、YAML 配置、pickle/JSON 转换、Markdown 工具、有界重试 | `logger`、`config`、`converter`、`markdown_utils`、`retry` |
| `fyuneru[redis]` | Redis client、Set 封装、checkpoint key 计算 | `redis_toolkit`、`redis_toolkit.init_client_from_config` |
| `fyuneru[s3]` | S3 client、对象读写删除列举、多源 `blob://` 读取 | `s3_toolkit`、`s3_source`、`s3_toolkit.init_client_from_config`、`s3_toolkit.init_workspace_from_config` |
| `fyuneru[gemini]` | Google Gemini client、视频输入构造、错误分类与结构化 JSON 输出 | `gemini_toolkit`、`gemini_toolkit.init_client_from_config` |
| `fyuneru[pipeline]` | Redis Streams 任务队列能力 | `task_queue` 及 `redis` 相关模块 |
| `fyuneru[media]` | 视频降采样（分辨率/帧率规约、只保留主视频流） | `video_toolkit` |

例如：

```bash
uv add "fyuneru[redis,s3] @ git+https://github.com/inklov3/fyuneru-pylib.git"
```

任何依赖可选第三方包的模块都应先安装对应 extra，例如 `fyuneru.redis_toolkit`、`fyuneru.s3_toolkit`、`fyuneru.task_queue`、`fyuneru.gemini_toolkit`。

## 模块概览

| 模块 | 说明 | 安装要求 |
| --- | --- | --- |
| `fyuneru.logger` | 基于 loguru 的日志初始化与 tqdm 集成 | 默认安装 |
| `fyuneru.config` | YAML 配置读取（含单层增量覆盖） | 默认安装 |
| `fyuneru.converter` | pickle 字节互转、任意对象转 JSON 兼容结构 | 默认安装 |
| `fyuneru.markdown_utils` | 去掉 Markdown 代码块包裹，保留正文 | 默认安装 |
| `fyuneru.retry` | 指数退避 + 拖动的有界重试，只重试显式声明的异常 | 默认安装 |
| `fyuneru.redis_toolkit` | Redis / RedisCluster 惰性初始化、Set 操作、checkpoint key 计算 | `redis` |
| `fyuneru.s3_toolkit` | MinIO Python SDK client 初始化、对象读写删除列举、预签名 URL 与对象探测 | `s3` |
| `fyuneru.s3_source` | 通过 `blob://桶id/key` 协议透明读取多个 S3 源 | `s3` |
| `fyuneru.task_queue` | Redis Streams broker、Actor 注册、消息投递与 Worker 消费 | `pipeline` |
| `fyuneru.gemini_toolkit` | Gemini client 初始化、视频输入、错误分类与结构化输出 | `gemini` |
| `fyuneru.video_toolkit` | 视频降采样为单流低规格 MP4，可版本化 `MediaProfile` | `media` |

## 文档

- [完整 API 指南](src/fyuneru/GUIDE.md)
- [通用模块参考与索引](docs/reference/00_overview.md)：按需阅读各模块参考，适用于所有开发者和 agent。
- [下游 pipeline 项目参考](docs/reference/40_pipeline_project.md)
- [仓库开发约定](AGENTS.md)

## 快速上手

### 日志

```python
from pathlib import Path

from fyuneru.logger import LogLevel, configure_logger, tqdm_loguru
from fyuneru.result import unwrap

unwrap(configure_logger(level=LogLevel.INFO, log_dir=Path("./logs")))

for item in tqdm_loguru(items, desc="Processing"):
    process(item)
```

### YAML 配置与按配置初始化

`read_config` / `read_config_with_override` 按 YAML 语义读取配置内容（当前不强制文件后缀）。完整配置结构见 [`example.yml`](example.yml)；使用时复制并替换占位值，删除不需要的配置段。

```python
from pathlib import Path

from fyuneru.config import (
    parse_redis_config,
    parse_s3_config,
    read_config,
    read_config_with_override,
)
from fyuneru.gemini_toolkit import init_client_from_config as init_llm_client
from fyuneru.redis_toolkit import init_client_from_config as init_redis_client
from fyuneru.s3_toolkit import init_client_from_config as init_s3_client
from fyuneru.s3_toolkit import init_workspace_from_config

cfg = read_config(Path("config.yml"))
cfg_with_pod = read_config_with_override(
    Path("config.yml"),
    Path("pod.yml"),
)

# 强类型配置解析（统一字段校验与报错路径）
redis_cfg = parse_redis_config(cfg_with_pod)
s3_cfg = parse_s3_config(cfg_with_pod)

# 底层 helper：返回裸 client 工厂
redis = init_redis_client(cfg_with_pod)()
s3_client = init_s3_client(cfg_with_pod)()
llm = init_llm_client(cfg_with_pod)()

# 高层 helper：直接绑定配置中的 bucket
write, read, delete = init_workspace_from_config(cfg_with_pod)()
```

### Pod YAML 增量覆盖规则

`read_config_with_override(base, override)` 使用以下规则：

- `dict`：递归合并，同名键由 override 覆盖
- 标量：override 直接替换 base
- `list`：默认追加（`base + override`）
- `s3_sources` 在该层仍按 list 追加；若需要按 `source_id` 去重，请在 `load_source_registry` 阶段处理

当前不支持模板变量渲染、字段删除语义（例如用 `null` 删除 base 字段）。

### Redis：Set 与 checkpoint

```python
from fyuneru.redis_toolkit import (
    bind_redis_set_deleter,
    bind_redis_set_reader,
    bind_redis_set_writer,
    calculate_checkpoint_key,
    init_client_standalone,
)
from fyuneru.result import unwrap

redis = init_client_standalone(
    host="localhost",
    port=6379,
    db=0,
    password="secret",
)()

checkpoint_key = calculate_checkpoint_key(
    workspace="ws-a",
    label="step1",
)
write_set = bind_redis_set_writer(redis, set_name=checkpoint_key)
read_set = bind_redis_set_reader(redis, set_name=checkpoint_key)
delete_set = bind_redis_set_deleter(redis, set_name=checkpoint_key)

unwrap(write_set("item-001"))
assert unwrap(read_set("item-001")) is True
unwrap(delete_set("item-001"))
```

### S3 对象存储

`s3_toolkit` 基于 MinIO Python SDK（`Minio`）公开接口，而非 boto3/botocore。endpoint 支持 http(s) scheme 与端口，不支持路径；`addressing_style` 默认 `virtual`，可设为 `path`。

- `bind_s3_writer` 使用 MinIO `put_object(length=-1, part_size=10 MiB)`；reader 消费后关闭 response 并释放连接，lister 递归列举，probe 使用 `stat_object`。

```python
from io import BytesIO

from fyuneru.result import unwrap
from fyuneru.s3_toolkit import (
    bind_s3_deleter,
    bind_s3_lister,
    bind_s3_reader,
    bind_s3_writer,
    init_client,
)

client = init_client(
    endpoint="https://s3.example.com",
    access_key_id="ak",
    secret_access_key="sk",
    region_name="us-east-1",
    addressing_style="path",  # 默认 "virtual"，也可设为 "path"
)()

write = bind_s3_writer(client, bucket="my-bucket")
read = bind_s3_reader(client, bucket="my-bucket")
delete = bind_s3_deleter(client, bucket="my-bucket")
lister = bind_s3_lister(client, bucket="my-bucket")

unwrap(write("demo.txt", BytesIO(b"hello")))
data = unwrap(read("demo.txt", lambda body: body.read()))
keys = unwrap(lister(prefix="data/", suffix=".parquet"))
unwrap(delete("demo.txt"))
```

### S3 多源读取

通过 `blob://桶id/key` URI 透明访问多个 S3 源。协议和配置说明见 [`docs/s3_source_protocol.md`](docs/s3_source_protocol.md)。

```python
from pathlib import Path

from fyuneru.config import read_config_with_override
from fyuneru.result import unwrap
from fyuneru.s3_source import bind_source_reader, load_source_registry

# 无覆盖层
config = read_config_with_override(Path("config.yml"))
registry = load_source_registry(config)

# 带 Pod 覆盖层
config = read_config_with_override(
    Path("config.yml"),
    Path("pod.yml"),
)
registry = load_source_registry(config)
read = bind_source_reader(registry)

data = unwrap(read("blob://my-images/photos/2024/img001.jpg", lambda body: body.read()))
```

### 分布式任务

```python
from dataclasses import dataclass

from fyuneru.result import unwrap
from fyuneru.task_queue import actor, build_broker, new_message


@dataclass(frozen=True)
class Payload:
    item_id: str
    priority: int


namespace = "worker-a:{etl}"
broker = build_broker(redis_client, namespace=namespace)


@actor(
    broker,
    queue_name="default",
)
def process_item(payload: Payload):
    print(payload.item_id, payload.priority)


unwrap(process_item.send(Payload(item_id="item-1", priority=3)))

batch_results = broker.enqueue_many(
    [
        new_message(
            queue_name="default",
            payload=Payload(item_id="item-2", priority=1),
        ),
        new_message(
            queue_name="default",
            payload=Payload(item_id="item-3", priority=2),
        ),
    ],
)
for result in batch_results:
    unwrap(result)

unwrap(
    broker.run_worker(
        queue_name="default",
        block_ms=1000,
    )
)
```

### Gemini 视频标注与结构化输出

```python
from fyuneru.gemini_toolkit import (
    GeminiTransientError,
    VideoSource,
    bind_video_captioner,
    build_content_config,
    init_client,
    response_to_json_object,
    response_to_raw_dict,
)
from fyuneru.result import unwrap
from fyuneru.retry import RetryPolicy, retry_call

client = init_client(
    api_key="sk_xxxx",
    endpoint="https://api.example.com",
)()

captioner = bind_video_captioner(
    client,
    model="gemini-2.0-flash",
    content_config=build_content_config(
        schema=MyModel.model_json_schema(),
        system_instruction=system_prompt,
    ),
)

# 预签名 URL 让模型侧自行拉取，请求体不带视频字节
response = retry_call(
    operation=lambda: unwrap(captioner(prompt, VideoSource(uri=presigned_url))),
    policy=RetryPolicy(attempts=5, base_seconds=2.0),
    retry_on=(GeminiTransientError,),
    label="gemini_caption",
)

raw = response_to_raw_dict(response)        # 归档原始响应
result = response_to_json_object(response)  # 结构化结果
```

纯文本结构化输出仍可直接用 client：

```python
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

### 视频降采样

```python
from pathlib import Path

from fyuneru.video_toolkit import MediaProfile, downsample_video, probe_video

profile = MediaProfile(target_height=480, target_fps=1, version="v1")
stat = probe_video(Path("source.mp4"))

report = downsample_video(
    source=Path("source.mp4"),
    destination=Path("prepared") / profile.descriptor() / "video.mp4",
    profile=profile,
    threads=2,
    max_output_bytes=100 * 1024 * 1024,
)
```

输出只保留一条视频流，音频与 DJI 预览/data 轨全部丢弃；`profile.descriptor()` 可直接拼进对象存储 key，避免规格变更后静默复用旧产物。

### 有界重试

```python
from fyuneru.retry import RetryPolicy, bind_retrying, retry_call

# 只重试瞬时错误，永久错误立即透传
value = retry_call(
    operation=lambda: call_upstream(),
    policy=RetryPolicy(attempts=3, base_seconds=1.0, max_seconds=30.0),
    retry_on=(TransientError,),
    label="call_upstream",
)

# 包成 ResultE
execute = bind_retrying(retry_on=(TransientError,))
result = execute(lambda: call_upstream())
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
uv sync --group dev --extra redis --extra s3 --extra gemini --extra pipeline --extra media
```

发布前检查：

```bash
./pre_release.sh
```

脚本会先同步完整开发/可选依赖，再顺序执行：

```bash
uv sync --group dev --extra redis --extra s3 --extra gemini --extra pipeline --extra media
uv run pyclean src/
uv run ruff check src/
uv run pyrefly check src/
uv run python test/test_s3_source.py
uv run python test/test_s3_toolkit.py
uv run python test/test_logger.py
uv run python test/test_config.py
uv run python test/test_retry.py
uv run python test/test_gemini_toolkit.py
uv run python test/test_video_toolkit.py
uv run python test/test_task_queue.py
```

当前仓库测试通过脚本执行，不是 pytest 工作流。

使用 Podman 构建包含所有可选依赖的基础镜像：

```bash
podman build -f Containerfile.base -t fyuneru-base .
```

构建上下文由 `.containerignore` 控制。

包源码位于 `src/fyuneru/`。

## 相关文件

- 配置示例：[`example.yml`](example.yml)
- 协议文档：[`docs/s3_source_protocol.md`](docs/s3_source_protocol.md)
- 任务队列设计：[`docs/task_queue_design.md`](docs/task_queue_design.md)

## License

Private
