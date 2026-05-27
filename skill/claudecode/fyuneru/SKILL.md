---
name: fyuneru
description: fyuneru / fyuneru-pylib Python 工具库的 API 索引。当用户的代码出现 from fyuneru / import fyuneru、用户对话提到 fyuneru / fyuneru-pylib，或在讨论本库封装的 Redis Set / S3 对象存储 / Mongo / Redis Streams 任务队列 / Gemini 客户端时触发。触发后先读 references/00_overview.md 与 references/01_result.md，再按需读对应模块 ref。
---

# fyuneru — API 索引（Claude Code Skill）

`fyuneru-pylib` 是 Python 基础设施工具库，把 Redis / S3 / Mongo / Gemini / Redis Streams 任务队列等组件封装成统一的 `init_* / bind_* / build_*` 组合接口，错误用 `fyuneru.result.Result` 显式返回。

## 使用方式

在写任何 `fyuneru.*` 调用代码前，按以下顺序加载上下文：

1. **必读**：`references/00_overview.md`（约定、extra 矩阵、配置 YAML 全貌）
2. **必读**：`references/01_result.md`（错误模型 —— 所有 toolkit 都返回 `ResultE[T]`）
3. **按需**：根据用户实际使用的模块读对应 reference

避免一次性把所有 ref 全读进上下文 —— 用户只用 redis 时不需要 gemini 的 API。

## Reference 目录

按模块拆分（前缀 0x 通用 / 1x 默认安装 / 2x 可选 toolkit / 3x pipeline）：

| Reference | 模块 | 安装要求 | 主题 |
| --- | --- | --- | --- |
| [`references/00_overview.md`](references/00_overview.md) | — | — | 项目定位、init/bind/build 约定、extra 矩阵、配置 YAML 全貌 |
| [`references/01_result.md`](references/01_result.md) | `fyuneru.result` | 默认 | `Result / Success / Failure / @safe / unwrap` |
| [`references/10_logger.md`](references/10_logger.md) | `fyuneru.logger` | 默认 | loguru 配置 + tqdm 集成 |
| [`references/11_config.md`](references/11_config.md) | `fyuneru.config` | 默认 | YAML 读取、单层覆盖、类型化解析器 |
| [`references/12_converter.md`](references/12_converter.md) | `fyuneru.converter` | 默认 | pickle 互转 + JSON 兼容结构 |
| [`references/13_markdown_utils.md`](references/13_markdown_utils.md) | `fyuneru.markdown_utils` | 默认 | 代码块剥壳 |
| [`references/20_redis_toolkit.md`](references/20_redis_toolkit.md) | `fyuneru.redis_toolkit` | `[redis]` | Redis 客户端 + Set 操作 + checkpoint key |
| [`references/21_s3_toolkit.md`](references/21_s3_toolkit.md) | `fyuneru.s3_toolkit` | `[s3]` | S3 client + 对象读写删除列举 |
| [`references/22_s3_source.md`](references/22_s3_source.md) | `fyuneru.s3_source` | `[s3]` | `blob://` 多源透明读取 |
| [`references/23_mongo_toolkit.md`](references/23_mongo_toolkit.md) | `fyuneru.mongo_toolkit` | `[mongo]` | MongoClient + ensure_index |
| [`references/24_gemini_toolkit.md`](references/24_gemini_toolkit.md) | `fyuneru.gemini_toolkit` | `[gemini]` | Gemini client + 结构化输出 |
| [`references/30_task_queue.md`](references/30_task_queue.md) | `fyuneru.task_queue` | `[pipeline]` | Redis Streams broker / actor / worker / xq |
| [`references/31_dramatiq_toolkit.md`](references/31_dramatiq_toolkit.md) | `fyuneru.dramatiq_toolkit` | `[pipeline]` | Dramatiq 批量入队辅助 |
| [`references/32_worker_env.md`](references/32_worker_env.md) | `fyuneru.worker` | 按启用资源 | `setup_worker_env` + result key 约定 |
| [`references/40_pipeline_project.md`](references/40_pipeline_project.md) | 项目骨架 | `[pipeline]` + 按资源 extra | WorkerEnv + task_queue 多节点/单节点 pipeline 搭建 |

## 触发后的工作流

1. 看用户代码里出现哪些 `fyuneru.<sub>` 子模块导入 → 决定读哪些 ref
2. 加载 ref 后再动手写代码；不要凭印象写签名
3. 写完代码前自查：
   - 所有可能失败的调用都用 `unwrap()` 或 `is_failure()` 分支处理
   - 用了对应 extra（如用 `redis_toolkit` 则 `pyproject.toml` 需 `fyuneru[redis]`）
   - 遵守模块特定约束（如 `task_queue` actor 必须单 dataclass payload、`configure_logger` 会清空 sink 等）
