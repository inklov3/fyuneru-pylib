# fyuneru.worker

下游 worker 进程的环境装配：按 config 段存在与否惰性创建 redis / s3 / mongo / source_reader。

需要：按启用资源安装对应 extra（`redis` / `s3` / `mongo`）

## API

```python
from fyuneru.worker import (
    WorkerEnv,
    setup_worker_env,
    calculate_checkpoint_key,
    calculate_result_key,
)

setup_worker_env(label: str, config: dict[str, Any], *, workspace: str) -> WorkerEnv
# 构建 worker 环境，按可选资源装配。
# 要求显式传入非空 workspace；redis / s3 / mongo / source_reader 只在 config 对应段存在时创建。
# s3_writer 接受 BinaryIO；s3_reader/source_reader 返回 StreamingBody，调用方负责 close。

calculate_checkpoint_key(workspace: str, label: str) -> str
# "{workspace}:checkpoint:{label}"  —— 与 redis_toolkit 同名函数同义

calculate_result_key(workspace: str, key: str, artifact: str) -> str
# "{workspace}/result/{key}/{artifact}.pkl"  —— S3 制品 key 约定
```

## 关键约束

- `setup_worker_env` 不会因为某段 config 缺失而抛错；只是对应资源不创建（WorkerEnv 字段为 None）。调用方使用前应做 None 检查
- `s3_reader` / `source_reader` 返回流对象后不会自动关闭；调用方必须使用 `with` 或显式 `close()`
- `calculate_result_key` 用 `.pkl` 后缀是默认约定，配合 `fyuneru.converter.unsafe_object_to_bytes` 使用（仅可信内部）
- 改本模块或 redis/s3/mongo 绑定逻辑时手动跑 `uv run python test/test_worker_env.py`
