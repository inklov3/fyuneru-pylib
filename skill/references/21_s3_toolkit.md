# fyuneru.s3_toolkit

S3 client 初始化与对象读写删除列举。

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
)

init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config: Config | None = None,     # botocore.config.Config
    addressing_style: str = "virtual",
) -> Callable[[], S3Client]
# 默认 config: signature_version="s3v4"
# addressing_style: "virtual" | "path"

init_client_from_config(config: dict) -> Callable[[], S3Client]
# 读 config["s3"]，不强制要 bucket。
# 缺 "s3" 段抛 KeyError。

init_workspace_from_config(config: dict) -> Callable
# 读 config["s3"]，必须含 bucket，缺立刻抛 KeyError。
# 返回 Callable[[], tuple[writer, reader, deleter]]。
```

## bind_* 操作

```python
bind_s3_writer(client, bucket: str) -> ObjectStorageWriter
# writer(key: str, body: BinaryIO) -> ResultE[None] — upload_fileobj

bind_s3_reader(client, bucket: str) -> ObjectStorageReader
# reader(key: str, consume: Callable[[ReadableBinaryStream], T]) -> ResultE[T]
# get_object、consume(body)、body.close() 都在 @safe 边界内执行。
# consume 必须同步消费流，不要保存或返回 body 给外部继续读取。

bind_s3_deleter(client, bucket: str) -> ObjectStorageDeleter
# deleter(key: str) -> ResultE[None]               — delete_object

bind_s3_lister(client, bucket: str) -> ObjectStorageLister
# lister(prefix: str, suffix: str | None = None) -> ResultE[list[str]]
# 自动用 list_objects_v2 + ContinuationToken 分页。
# 服务端返回 IsTruncated=True 但缺 NextContinuationToken 时抛 RuntimeError
# 并带 prefix，防止死循环。
# 过滤掉目录占位符（key 以 "/" 结尾）。
# 可选 suffix 在客户端侧过滤。
```

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

## 关键约束

- `init_client_from_config` 与 `init_workspace_from_config` 的区别：前者不校验 bucket，后者强制
- `bind_s3_reader` 不返回裸流；读取、写本地文件、解码等操作应放在 `consume` 内同步完成
- `bind_s3_writer` 只接受文件类对象；小对象可用 `io.BytesIO` 包装
