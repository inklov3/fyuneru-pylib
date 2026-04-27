# AGENTS.md — fyuneru-pylib

## 这个仓库最容易踩坑的点

- 使用 **uv**（不是 pip/poetry）。
- 这是 `src/` 布局的库项目（`src/fyuneru`），不是可运行应用。
- 顶层 `src/fyuneru/__init__.py` 为空；不要假设顶层 re-export，按子模块导入。
- 测试不是 pytest：都是 `test/*.py` 脚本（`assert` + `__main__`）。

## 权威命令（以脚本/配置为准）

### 安装

```bash
# 开发最小安装
uv sync --group dev

# 开发 + 全部可选能力
uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media
```

### 代码改动后最小校验顺序

```bash
uv run ruff check src/
uv run ruff format src/
uv run pyrefly check src/
```

### 完整发布前校验（单一真相）

```bash
./pre_release.sh
```

`pre_release.sh` 当前顺序是：
1) `uv sync ...all extras`
2) `uv run pyclean src/`
3) `uv run ruff check src/`
4) `uv run pyrefly check src/`
5) `uv run python test/test_s3_source.py`
6) `uv run python test/test_logger.py`
7) `uv run python test/test_config.py`
8) `uv run python test/test_task_queue.py`

## 测试约定

```bash
# 单测脚本
uv run python test/test_logger.py
uv run python test/test_s3_source.py
uv run python test/test_config.py
uv run python test/test_task_queue.py

# 全量脚本测试
uv run python test/test_s3_source.py && uv run python test/test_logger.py && uv run python test/test_config.py && uv run python test/test_task_queue.py
```

- `task_queue.run_worker` 是无限循环消费；写测试/本地验证时避免直接调用它导致阻塞。
- 现有测试都走纯逻辑路径，不依赖外部 Redis/S3/Mongo 服务（`test_task_queue.py` 使用 fake client）。

## 结构与边界（只保留会影响实现决策的事实）

- 核心模式：
  - `init_*`：返回惰性 `Callable[[], Client]`
  - `bind_*`：绑定 client + 资源名，返回单一操作闭包
  - `build_*`：构建组合对象（如 broker）
- 统一错误模型：`src/fyuneru/result.py`
  - `Success` / `Failure` / `@safe` / `unwrap`
- 配置读取：`src/fyuneru/config.py`
  - `read_config_from_paths` 按顺序合并多个 YAML
  - merge 规则：`dict` 递归合并、标量覆盖、`list` 直接追加
  - `read_config_from_env` 读取 `FYUNERU_CONFIG_PATHS`（冒号分隔）
- `task_queue`：`src/fyuneru/task_queue/`
  - payload 强约束为 dataclass envelope（fail-fast）
  - 重试/死信 + ACK 关键迁移优先走 Lua 脚本

## 可选依赖边界（不要猜依赖存在）

- `redis_toolkit` 需要 `fyuneru[redis]`
- `s3_toolkit` / `s3_source` 需要 `fyuneru[s3]`
- `mongo_toolkit` 需要 `fyuneru[mongo]`
- `gemini_toolkit` 需要 `fyuneru[gemini]`
- `task_queue` 需要 `fyuneru[pipeline]`

## 仓库约定

- 注释/docstring 使用中文；代码标识符使用英文。
- commit message 使用中文并带前缀：`fix:` / `feat:` / `refactor:` / `doc:` / `style:`。
