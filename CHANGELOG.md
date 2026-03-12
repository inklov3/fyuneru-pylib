# Changelog

## 2026-03-12

### 新增

- **`config.py`** — 新增 `read_config_with_override(base, override)`，支持单层 YAML 增量覆盖
  - `dict` 递归合并
  - 标量后者覆盖
  - `list` 默认追加
  - `s3_sources` 特例按 `source_id` 去重，重复时后者覆盖
- **`s3_source.py`** — `load_source_registry` 增加 `override_path` 参数，复用配置覆盖逻辑

### 测试

- **`test/test_config.py`** — 新增配置增量覆盖测试
- **`test/test_s3_source.py`** — 新增 `load_source_registry(base, override)` 用例

### 文档

- **`README.md`** — 新增 Pod YAML 增量覆盖说明、规则与非目标说明
- **`docs/s3_source_protocol.md`** — 增补 `override_path` 使用方式与 `s3_sources` 冲突规则

## 2026-03-10

### 功能

- **`config.py`** — `init_redis_from_config` 支持可选 `password` 字段，透传至 Redis 客户端

### 重构

- **`mongo_toolkit.py`** — `init_client` 还原为只返回 `Callable[[], MongoClient]`，去掉 `db` 参数，与其他 toolkit 的 `init_*` 保持一致
- **`config.py`** — 拆分为两层：
  - 底层 `init_*_from_config`：返回裸客户端工厂（`init_s3_from_config` → `S3Client`，`init_mongo_from_config` → `MongoClient`）
  - 高层 `init_*_workspace/database_from_config`：绑定配置中的 bucket/db，返回可直接使用的对象工厂
    - `init_s3_workspace_from_config` — 必选 `bucket`，返回 `(writer, reader, deleter)` 工厂
    - `init_mongo_database_from_config` — 必选 `db`，返回 `Database` 工厂

### 文档

- **`README.md`** / **`CLAUDE_GUIDE.md`** — 更新 API 签名和示例，体现两层 initializer 设计
- **`example.yml`** — `s3.bucket` 和 `mongo.db` 标注为高层函数必选

## 2026-03-09

### 新增

- **`s3_source.py`** — S3 多源协议模块，通过 `blob://桶id/key` URI 透明读取多个 S3 源
  - `parse_blob_uri` — 解析 `blob://桶id/key` → `(桶id, key)`
  - `load_source_registry` — 从配置文件 `s3_sources` 段加载源列表，转为以 `source_id` 为 key 的字典
  - `init_source_reader` — 返回闭包函数，按需懒初始化 client + reader 并缓存

### 文档

- **`docs/s3_source_protocol.md`** — S3 多源协议设计文档
- **`example.yml`** — 新增 `s3_sources` 多源配置示例
- **`README.md`** — 模块概览新增 `s3_source`；快速上手新增多源读取示例
- **`CLAUDE.md`** — Module Layout 新增 `s3_source.py`；修正 `config.py` 依赖描述
- **`CLAUDE_GUIDE.md`** — 新增 `s3_source` API 参考

### 测试

- **`test/test_s3_source.py`** — `parse_blob_uri` 正常/异常用例

## 2026-03-05 (4)

### 重构

- **`config.py`** — 去掉 TOML 支持（删除 `tomllib` 导入），`read_config` 仅接受 `.yaml` / `.yml`，其他后缀抛出 `ValueError`

### 新增

- **`config.py`** — 新增 4 个纯函数式 client 初始化函数：
  - `init_redis_from_config` — 从 `redis` 配置段构建 Redis client initializer（支持 standalone / cluster）
  - `init_s3_from_config` — 从 `s3` 配置段构建 S3 client initializer
  - `init_mongo_from_config` — 从 `mongo` 配置段构建 MongoDB client initializer
  - `init_llm_from_config` — 从 `llm` 配置段构建 LLM client initializer（目前支持 gemini）
  - 各 toolkit 延迟导入，避免未安装可选依赖时 import config 报错
  - 配置段缺失时直接抛出 `KeyError`
- **`example.yml`** — 新增 YAML 示例配置文件

### 文档

- **`README.md`** — config 模块说明更新为 YAML + client 初始化；补全从配置文件初始化各 client 的示例

## 2026-03-05 (3)

### 重构

- **`redis_toolkit.py`** — 删除 `gen_checkpointer` 及其三个 Protocol 类（`AdvanceCheckpoint`、`IsPastCheckpoint`、`DelCheckpoint`），检查点功能改由 `calculate_checkpoint_key` + `gen_redis_set` 组合实现，消除重复包装

### 文档

- **`README.md`** — 补全 `config`、`converter`、`markdown_utils`、`mongo_toolkit` 的快速上手示例；补充 `tqdm_loguru`、`gen_redis_set`、`calculate_namespace` 用法；检查点示例同步更新为组合写法

## 2026-03-05 (2)

代码设计与命名审视重构。

### 模块重命名

- `configger.py` → `config.py` — 去除不规范后缀
- `json_utils.py` → `markdown_utils.py` — 模块内容是 markdown 处理，非 JSON
- `distask_toolkit.py` → `dramatiq_toolkit.py` — 用底层框架名替代自造缩写
- `gemini_client.py` → `gemini_toolkit.py` — 统一 `*_toolkit` 后缀

### 函数重命名

- `dramatiq_toolkit`: `create_redis_broker` → `init_broker`（遵循 `init` 约定）
- `redis_toolkit`: `checkpoint_calculator` → `calculate_checkpoint_key`（统一动词前缀，`key` 更准确）
- `s3_toolkit`: `init_s3client` → `init_client`（去除冗余 `s3` 前缀）
- `gemini_toolkit`: `get_config` → `gen_content_config`（`gen` 前缀表明构造语义，避免过于泛化）

### 删除

- `gemini_toolkit`: 删除 `get_prompt`（单行 `Path.read_text()` 包装，无复用价值）及未使用的 `Path` 导入

### 修复

- `s3_toolkit`: `init_client` 的 `config` 参数从可变默认值改为 `Config | None = None`，函数体内按需初始化

## 2026-03-05

修复 README 代码复核清单中的全部 9 项问题。

### P0 — 运行时错误

- **`redis_toolkit.py`** — 删除对已删除模块 `fyuneru.checkpointer` 的导入，将 `AdvanceCheckpoint`、`IsPastCheckpoint`、`DelCheckpoint` 三个 Protocol 内联定义
- **`pyproject.toml`** — 合并重复的 `[dependency-groups] dev`，保留带版本约束的 `pyclean>=3.5.0`

### P1 — 经典缺陷

- **`distask_toolkit.py`** — `kwargs` 和 `options` 参数从可变默认值 `{}` 改为 `None`，函数体内按需初始化

### P2 — 命名 / 文档错误

- **`json_utils.py`** — 函数名拼写修正 `unwrap_codeblack` → `unwrap_codeblock`
- **`logger.py`** — docstring 移到函数签名正下方，使其能被正确识别
- **`gemini_client.py`** — docstring 中 `endpoint` 描述删除"默认为 None"，与实际必填参数一致

### P3 — 代码风格

- **`s3_toolkit.py`** — 删除无意义自赋值 `client: S3Client = client`
- **`redis_toolkit.py`** — 删除无意义自赋值 `set_name = set_name`
- **`logger.py`** — 变量名 `format` 重命名为 `log_format`，避免遮蔽内置函数
