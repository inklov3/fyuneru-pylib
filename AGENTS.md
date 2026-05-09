# AGENTS.md — fyuneru-pylib

## 先记住这些（最容易做错）
- 只用 `uv`，不要用 pip/poetry。
- 这是 `src/` 布局的**库项目**，源码在 `src/fyuneru/`，不是应用入口仓库。
- 顶层 `src/fyuneru/__init__.py` 为空；默认从子模块导入。
- 测试是脚本执行（`uv run python test/*.py`），不是 pytest 工作流。

## 安装与依赖边界
- 开发最小依赖：`uv sync --group dev`
- 需要可选能力时显式加 extra：
  `uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media`
- 不要假设可选依赖存在：
  - `redis_toolkit` → `fyuneru[redis]`
  - `s3_toolkit` / `s3_source` → `fyuneru[s3]`
  - `mongo_toolkit` → `fyuneru[mongo]`
  - `gemini_toolkit` → `fyuneru[gemini]`
  - `task_queue` / `dramatiq_toolkit` → `fyuneru[pipeline]`

## 权威校验命令（以可执行脚本为准）
- 完整发布前校验：`./pre_release.sh`
- `pre_release.sh` 当前顺序（不要改顺序假设）：
  1) `uv sync --group dev --extra redis --extra s3 --extra mongo --extra gemini --extra pipeline --extra media`
  2) `uv run pyclean src/`
  3) `uv run ruff check src/`
  4) `uv run pyrefly check src/`
  5) `uv run python test/test_s3_source.py`
  6) `uv run python test/test_logger.py`
  7) `uv run python test/test_config.py`
  8) `uv run python test/test_task_queue.py`
- 注意：仓库还有 `test/test_worker_env.py`，但**当前 pre_release 未覆盖**；改动 `fyuneru/worker/*` 或 `mongo/redis/s3` 绑定逻辑时请手动跑：
  `uv run python test/test_worker_env.py`

## 常用定向验证
- `uv run python test/test_logger.py`
- `uv run python test/test_s3_source.py`
- `uv run python test/test_config.py`
- `uv run python test/test_task_queue.py`
- `uv run python test/test_worker_env.py`

## 结构与约束（影响实现决策）
- 统一模式：`init_*`（返回惰性 initializer）/ `bind_*`（绑定资源返回单操作闭包）/ `build_*`（构建组合对象）。
- 统一错误模型：`src/fyuneru/result.py` 的 `Success` / `Failure` / `@safe` / `unwrap`。
- 配置读取：`src/fyuneru/config.py`
  - `read_config_from_paths` 按顺序合并多个 YAML
  - merge 规则：`dict` 递归合并、标量覆盖、`list` 追加
  - `read_config_from_env` 读取 `FYUNERU_CONFIG_PATHS`（冒号分隔）
- `s3_sources` 的去重不在 merge 阶段完成，而在 `load_source_registry`（重复 `source_id` 后者覆盖前者）。
- `task_queue` 关键约束：
  - `actor` handler 必须且仅能有一个 payload 参数，且类型必须是 dataclass
  - payload envelope 强校验在 `task_queue/codec.py`
  - `run_worker` 是无限循环；测试/本地验证优先用 `run_worker_once_for_test`

## 仓库约定
- 注释/docstring 使用中文；代码标识符使用英文。
- commit message 使用中文并带前缀：`fix:` / `feat:` / `refactor:` / `doc:` / `style:`。
