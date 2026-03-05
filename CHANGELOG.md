# Changelog

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
