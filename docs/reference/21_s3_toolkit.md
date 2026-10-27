# fyuneru.s3_toolkit

S3 client 初始化、对象读写删除列举、预签名 URL 与对象探测。

需要：`fyuneru[s3]`

## API

```python
from fyuneru.s3_toolkit import (
    init_client,
    init_client_from_config,
    init_workspace_from_config,
    bind_s3_writer,
    bind_s3_reader,
    bind_s3_deleter,
    bind_s3_lister,
    bind_s3_presigner,
    bind_s3_probe,
)

init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    addressing_style: str = "virtual",
) -> Callable[[], Minio]
# 返回惰性 MinIO Python SDK 客户端工厂；endpoint 可带 http(s) scheme 和端口，不可带路径/query/fragment。
# addressing_style: "virtual"（默认）| "path"。

init_client_from_config(config: dict) -> Callable[[], Minio]
# 读 config["s3"]，不强制要 bucket。
# 缺 "s3" 段抛 KeyError。

init_workspace_from_config(config: dict) -> Callable
# 读 config["s3"]，必须含 bucket，缺立刻抛 KeyError。
# 返回 Callable[[], tuple[writer, reader, deleter]]。
```

## bind_* 操作

```python
bind_s3_writer(client: Minio, bucket: str) -> ObjectStorageWriter
# writer(key: str, body: BinaryIO) -> ResultE[None] — MinIO put_object(length=-1, part_size=10 MiB)

bind_s3_reader(client: Minio, bucket: str) -> ObjectStorageReader
# reader(key: str, consume: Callable[[ReadableBinaryStream], T]) -> ResultE[T]
# get_object、consume(body)、body.close() 都在 @safe 边界内执行。
# consume 必须同步消费流，不要保存或返回 body 给外部继续读取。

bind_s3_deleter(client, bucket: str) -> ObjectStorageDeleter
# deleter(key: str) -> ResultE[None]               — remove_object

bind_s3_lister(client, bucket: str) -> ObjectStorageLister
# lister(prefix: str, suffix: str | None = None) -> ResultE[list[str]]
# 使用 MinIO list_objects(bucket, prefix=..., recursive=True) 处理递归列举与分页。
# 过滤掉目录占位符（key 以 "/" 结尾）。
# 可选 suffix 在客户端侧过滤。

bind_s3_presigner(client, bucket: str) -> ObjectStoragePresigner
# presign(key: str, expires_seconds: int = 3600) -> ResultE[str]
# 生成 get_object 预签名 URL。expires_seconds 必须为正数。
# 用于把对象交给无法持有凭证的外部服务（例如多模态模型拉取视频）。

bind_s3_probe(client, bucket: str) -> ObjectStorageProbe
# probe(key: str) -> ResultE[ObjectStat | None]
# 使用 stat_object；NoSuchKey / NoSuchObject / NotFound 返回 Success(None)，而不是 Failure。
# 鉴权失败、网络错误等仍然返回 Failure，不会被当成“不存在”。
```

## ObjectStat

```python
@dataclass(frozen=True)
class ObjectStat:
    key: str
    size_bytes: int
    etag: str | None          # 已剔掉包裹引号
    content_type: str | None
```

`etag` 可作为源对象的内容指纹记入派生产物的 provenance，用于判定源是否变更。

## 用法

```python
from io import BytesIO
from pathlib import Path

from fyuneru.result import unwrap

write = bind_s3_writer(client, bucket="my-bucket")
read = bind_s3_reader(client, bucket="my-bucket")

unwrap(write("small.txt", BytesIO(b"hello")))

def save_to_file(body):
    with Path("archive.zip").open("wb") as output:
        while chunk := body.read(1024 * 1024):
            output.write(chunk)

unwrap(read("archive.zip", save_to_file))
```

### 幂等复用：先探测再处理

```python
from fyuneru.result import unwrap
from fyuneru.s3_toolkit import bind_s3_probe

probe = bind_s3_probe(client, "workspace-bucket")
stat = unwrap(probe("prepared/v1-480p-1fps/video.mp4"))
if stat is not None and stat.size_bytes > 0:
    # 派生产物已存在，跳过重新转码
    reuse(stat)
else:
    produce()
```

### 预签名 URL 交给外部服务

```python
from fyuneru.gemini_toolkit import VideoSource
from fyuneru.result import unwrap
from fyuneru.s3_toolkit import bind_s3_presigner

presign = bind_s3_presigner(client, "workspace-bucket")
# 有效期需覆盖排队时间 + 模型拉取时间
url = unwrap(presign("prepared/v1-480p-1fps/video.mp4", expires_seconds=7200))
source = VideoSource(uri=url)
```

## 关键约束

- `init_client_from_config` 与 `init_workspace_from_config` 的区别：前者不校验 bucket，后者强制
- `bind_s3_reader` 在消费结束后调用响应的 `close()` 与 `release_conn()`，确保连接资源释放
- `bind_s3_writer` 接收二进制文件流；MinIO SDK 以 `length=-1`、`part_size=10 MiB` 调用 `put_object`，流长度未知时可分段上传；小对象可用 `io.BytesIO` 包装
- `bind_s3_probe` 把"对象不存在"当正常结果（`Success(None)`），只有真正的错误才是 `Failure`；调用方必须区分两者
- 预签名 URL 的有效期需覆盖下游消费的完整窗口（排队 + 拉取），过短会在高负载下随机失败
- 预签名 URL 包含签名，不得当作稳定身份标识持久化或归档
