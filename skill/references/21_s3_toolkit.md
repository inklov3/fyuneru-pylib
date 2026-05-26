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
    bind_s3_chunked_reader,
    bind_s3_stream_reader,
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
# writer(key: str, body: bytes) -> ResultE[None]   — put_object

bind_s3_reader(client, bucket: str) -> ObjectStorageReader
# reader(key: str) -> ResultE[bytes]               — get_object
# 警告：全量读入内存，大文件请用 chunked/stream 版本，否则 OOM。

bind_s3_chunked_reader(client, bucket: str, chunk_size: int = 1024 * 1024) -> ObjectStorageChunkedReader
# reader(key: str) -> ResultE[Iterator[bytes]]
# 按 chunk_size 迭代；迭代器消费完 / 抛错时自动 close socket。
# 返回的迭代器只能消费一次。chunk_size 必须 > 0。

bind_s3_stream_reader(client, bucket: str) -> ObjectStorageStreamReader
# reader(key: str) -> ResultE[StreamingBody]
# 把 boto3 的 StreamingBody 原样交回，适合转给非 boto3 库（视频解码器等）。
# 调用方必须 with closing(body): 使用，避免 socket 泄漏。

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

## 关键约束

- `init_client_from_config` 与 `init_workspace_from_config` 的区别：前者不校验 bucket，后者强制
- 大文件读取**必须**用 chunked 或 stream 版本；`bind_s3_reader` 是为小对象准备的便捷接口
- `bind_s3_stream_reader` 返回的 `StreamingBody` 责任在调用方（要 close）
