from __future__ import annotations

import weakref
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Protocol, cast

from boto3 import Session
from botocore.config import Config
from botocore.response import StreamingBody

from fyuneru.config import parse_s3_config
from fyuneru.result import ResultE, safe

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


class ObjectStorageWriter(Protocol):
    def __call__(self, key: str, body: bytes) -> ResultE[None]: ...


class ObjectStorageReader(Protocol):
    def __call__(self, key: str) -> ResultE[bytes]: ...


class ObjectStorageChunkedReader(Protocol):
    def __call__(self, key: str) -> ResultE[Iterator[bytes]]: ...


class ObjectStorageStreamReader(Protocol):
    def __call__(self, key: str) -> ResultE[StreamingBody]: ...


class ObjectStorageDeleter(Protocol):
    def __call__(self, key: str) -> ResultE[None]: ...


class ObjectStorageLister(Protocol):
    def __call__(
        self,
        prefix: str,
        suffix: str | None = None,
    ) -> ResultE[list[str]]: ...


def init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config: Config | None = None,
    addressing_style: str = "virtual",
) -> Callable[[], S3Client]:
    if config is None:
        config = Config(
            signature_version="s3v4",
            s3=cast(Any, {"addressing_style": addressing_style}),
        )
    session: Session = Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
    )

    def create_client() -> S3Client:
        return session.client(
            service_name="s3",
            endpoint_url=endpoint,
            config=config,
        )

    return create_client


def init_client_from_config(config: dict) -> Callable[[], S3Client]:
    """从配置构建 s3 client initializer。

    config["s3"] 必须包含 endpoint, access_key_id, secret_access_key。可选: region_name。
    """
    s3_cfg = parse_s3_config(config)
    return init_client(
        endpoint=s3_cfg.endpoint,
        access_key_id=s3_cfg.access_key_id,
        secret_access_key=s3_cfg.secret_access_key,
        region_name=s3_cfg.region_name,
        addressing_style=s3_cfg.addressing_style,
    )


def init_workspace_from_config(
    config: dict,
) -> Callable[
    [], tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]
]:
    """从配置构建 s3 workspace initializer。

    config["s3"] 必须包含 endpoint, access_key_id, secret_access_key, bucket。可选: region_name。
    返回可直接使用的 (writer, reader, deleter) 元组工厂。
    """
    s3_cfg = parse_s3_config(config)
    if s3_cfg.bucket is None:
        raise KeyError("缺少字段: s3.bucket")

    init = init_client(
        endpoint=s3_cfg.endpoint,
        access_key_id=s3_cfg.access_key_id,
        secret_access_key=s3_cfg.secret_access_key,
        region_name=s3_cfg.region_name,
        addressing_style=s3_cfg.addressing_style,
    )
    bucket = s3_cfg.bucket

    def create_workspace():
        client = init()
        return (
            bind_s3_writer(client, bucket),
            bind_s3_reader(client, bucket),
            bind_s3_deleter(client, bucket),
        )

    return create_workspace


def bind_s3_writer(client: S3Client, bucket: str) -> ObjectStorageWriter:
    @safe
    def write_object(key: str, body: bytes) -> None:
        client.put_object(Bucket=bucket, Key=key, Body=body)

    return write_object


def bind_s3_reader(client: S3Client, bucket: str) -> ObjectStorageReader:
    """全量读取 S3 对象到 bytes。

    **警告：把整个对象读入内存**，大文件请改用 :func:`bind_s3_chunked_reader` 或
    :func:`bind_s3_stream_reader`，否则随时会 OOM。
    """

    @safe
    def read_object(key: str) -> bytes:
        response = client.get_object(Bucket=bucket, Key=key)
        body: StreamingBody = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    return read_object


def bind_s3_stream_reader(
    client: S3Client, bucket: str
) -> ObjectStorageStreamReader:
    """以 :class:`StreamingBody` 形式返回对象，调用方负责 ``close()``。

    适合需要把 body 转交给 boto3 之外的库（例如视频解码器）的场景。建议配合
    ``with closing(body):`` 使用，避免 socket 泄漏。
    """

    @safe
    def open_stream(key: str) -> StreamingBody:
        response = client.get_object(Bucket=bucket, Key=key)
        return response["Body"]

    return open_stream


def bind_s3_chunked_reader(
    client: S3Client,
    bucket: str,
    chunk_size: int = 1024 * 1024,
) -> ObjectStorageChunkedReader:
    """按固定块大小迭代 S3 对象，迭代器消耗完毕后自动关闭底层连接。

    返回的迭代器只能消费一次；遍历到末尾或显式 ``close()`` 后再次迭代会得到空序列。
    若调用方拿到迭代器后从未启动遍历，generator finally 不会触发；这里额外挂一个
    :func:`weakref.finalize` 作为兜底，迭代器被 GC 时也会关闭 body。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    @safe
    def open_chunks(key: str) -> Iterator[bytes]:
        response = client.get_object(Bucket=bucket, Key=key)
        body: StreamingBody = response["Body"]
        generator = _iter_chunks(body, chunk_size)
        weakref.finalize(generator, body.close)
        return generator

    return open_chunks


def _iter_chunks(body: StreamingBody, chunk_size: int) -> Iterator[bytes]:
    try:
        for chunk in body.iter_chunks(chunk_size=chunk_size):
            if not chunk:
                continue
            yield chunk
    finally:
        body.close()


def bind_s3_deleter(client: S3Client, bucket: str) -> ObjectStorageDeleter:
    @safe
    def delete_object(key: str) -> None:
        client.delete_object(Bucket=bucket, Key=key)

    return delete_object


def bind_s3_lister(client: S3Client, bucket: str) -> ObjectStorageLister:
    @safe
    def list_objects(prefix: str, suffix: str | None = None) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict = {"Bucket": bucket, "Prefix": prefix}
            if continuation_token is not None:
                kwargs["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**kwargs)
            for obj in response.get("Contents", []):
                key = obj.get("Key")
                if key is None:
                    continue
                if key.endswith("/"):
                    continue
                if suffix is not None and not key.endswith(suffix):
                    continue
                keys.append(key)
            if not response.get("IsTruncated", False):
                break
            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                raise RuntimeError(
                    "S3 list_objects_v2 报告 IsTruncated=True 但未返回 "
                    f"NextContinuationToken (prefix={prefix})"
                )
        return keys

    return list_objects
