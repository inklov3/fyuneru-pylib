# Changelog

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
