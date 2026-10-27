# fyuneru 概览

Python 工具库，把 Redis / S3 / Redis Streams 任务队列 / Gemini 等基础设施访问整理成更小、更稳定的组合单元。Python `>= 3.14`。

## 核心约定（贯穿所有 toolkit）

- **`init_*`**：返回 `Callable`，调用时才真正创建 client 或 handle（惰性）
- **`bind_*`**：绑定 client + 资源名，返回单一操作函数（闭包）
- **`build_*`**：构建已绑定的组合对象
- **`@safe`**：把可能失败的操作包装成 `ResultE[...]`；需要值时使用 `unwrap(result)`（详见 `01_result.md`）
- **顶层 `fyuneru` 不提供统一 re-export**，必须从具体子模块导入：`from fyuneru.redis_toolkit import bind_redis_set_writer`

## 安装与 extra 边界

```bash
uv add fyuneru@git+https://github.com/inklov3/fyuneru-pylib.git
```

| extra | 启用模块 |
| --- | --- |
| 默认安装 | `logger`、`config`、`converter`、`markdown_utils`、`result`、`retry` |
| `fyuneru[redis]` | `redis_toolkit` |
| `fyuneru[s3]` | `s3_toolkit`、`s3_source` |
| `fyuneru[gemini]` | `gemini_toolkit` |
| `fyuneru[pipeline]` | `task_queue` |
| `fyuneru[media]` | `video_toolkit`（需 `av`） |

```bash
uv add "fyuneru[redis,s3] @ git+https://github.com/inklov3/fyuneru-pylib.git"
```

写代码前先确认 `pyproject.toml` 装了对应 extra，否则 import 时 ModuleNotFoundError。

## 模块速查（详见对应 reference）

| reference | 模块 | 安装 |
| --- | --- | --- |
| `01_result.md` | `fyuneru.result` | 默认 |
| `10_logger.md` | `fyuneru.logger` | 默认 |
| `11_config.md` | `fyuneru.config` | 默认 |
| `12_converter.md` | `fyuneru.converter` | 默认 |
| `13_markdown_utils.md` | `fyuneru.markdown_utils` | 默认 |
| `15_retry.md` | `fyuneru.retry` | 默认 |
| `20_redis_toolkit.md` | `fyuneru.redis_toolkit` | `[redis]` |
| `21_s3_toolkit.md` | `fyuneru.s3_toolkit` | `[s3]` |
| `22_s3_source.md` | `fyuneru.s3_source` | `[s3]` |
| `24_gemini_toolkit.md` | `fyuneru.gemini_toolkit` | `[gemini]` |
| `25_video_toolkit.md` | `fyuneru.video_toolkit` | `[media]` |
| `30_task_queue.md` | `fyuneru.task_queue` | `[pipeline]` |
| `32_worker_env.md` | `fyuneru.worker` | 按启用资源 |

### S3 SDK 行为

`fyuneru.s3_toolkit` 使用 MinIO Python SDK 的 `Minio` 客户端，不接受 boto3/botocore 的 Config。endpoint 可带 `http(s)://` 与端口，不可带路径、query 或 fragment；未写 scheme 时按 HTTPS 处理。`addressing_style` 默认为 `virtual`，也可选 `path`。对象读写和列表等具体行为见 [`21_s3_toolkit.md`](21_s3_toolkit.md)。

```yaml
redis:
  host: localhost
  port: 6379
  db: 0             # optional, default 0
  cluster: false     # optional, default false
  password: xxx      # optional

s3:
  endpoint: https://s3.example.com
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1     # optional
  bucket: my-bucket          # init_workspace_from_config 必需
  addressing_style: path  # optional: path (default) | virtual


llm:
  provider: gemini
  api_key: xxx
  endpoint: https://api.example.com
  api_version: v1beta

s3_sources:                  # optional, blob:// 多源
- source_id: my-images
  endpoint: https://s3.example.com
  bucket: actual-bucket-name
  access_key_id: xxx
  secret_access_key: xxx
  region_name: us-east-1
```

## 配置驱动初始化（典型骨架）

```python
from pathlib import Path

from fyuneru.config import read_config_with_override
from fyuneru.gemini_toolkit import init_client_from_config as init_llm_client
from fyuneru.redis_toolkit import init_client_from_config as init_redis_client
from fyuneru.s3_toolkit import init_client_from_config as init_s3_client
from fyuneru.s3_toolkit import init_workspace_from_config

cfg = read_config_with_override(base=Path("config.yml"), override=Path("pod.yml"))

redis = init_redis_client(cfg)()
s3_client = init_s3_client(cfg)()
llm = init_llm_client(cfg)()
s3_writer, s3_reader, s3_deleter = init_workspace_from_config(cfg)()
```
