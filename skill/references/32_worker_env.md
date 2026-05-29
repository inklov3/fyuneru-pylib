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
# s3_writer 接受 BinaryIO；s3_reader/source_reader 使用受控消费式读取。

calculate_checkpoint_key(workspace: str, label: str) -> str
# "{workspace}:checkpoint:{label}"  —— 与 redis_toolkit 同名函数同义

calculate_result_key(workspace: str, key: str, artifact: str) -> str
# "{workspace}/result/{key}/{artifact}.pkl"  —— S3 制品 key 约定
```

## reader 语义

```python
def consume(body):
    return body.read(1024)

result = env.s3_reader("object/key", consume)
result = env.source_reader("blob://source-id/object/key", consume)
```

- `s3_reader` 的 key 是目标 S3 bucket 内 object key。
- `source_reader` 的 key 是源 URI，例如 `blob://source-id/path/to/object`。
- 当前 `source_reader` 由 `s3_source.bind_source_reader` 基于 `ObjectStorageReader` 组合实现；后续增加 file/http 等来源时再引入更通用的 `SourceReader` Protocol。

## 关键约束

- `setup_worker_env` 不会因为某段 config 缺失而抛错；只是对应资源不创建（WorkerEnv 字段为 None）。调用方使用前应做 None 检查
- `s3_reader` / `source_reader` 不返回裸流；读取、写本地文件、解码等操作应放在 `consume` 内同步完成
- `calculate_result_key` 用 `.pkl` 后缀是默认约定，配合 `fyuneru.converter.unsafe_object_to_bytes` 使用（仅可信内部）
- 改本模块或 redis/s3/mongo 绑定逻辑时手动跑 `uv run python test/test_worker_env.py`
