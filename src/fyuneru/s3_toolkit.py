from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO, Protocol, TypeVar, overload
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from fyuneru.config import parse_s3_config
from fyuneru.result import ResultE, safe

T = TypeVar("T")


class ReadableBinaryStream(Protocol):
    @overload
    def read(self, amt: int) -> bytes: ...

    @overload
    def read(self, amt: None = None) -> bytes: ...

    def read(self, amt: int | None = None) -> bytes: ...

    def close(self) -> None: ...


class ObjectStorageWriter(Protocol):
    def __call__(self, key: str, body: BinaryIO) -> ResultE[None]: ...


class ObjectStorageReader(Protocol):
    def __call__(
        self, key: str, consume: Callable[[ReadableBinaryStream], T]
    ) -> ResultE[T]: ...


class ObjectStorageDeleter(Protocol):
    def __call__(self, key: str) -> ResultE[None]: ...


class ObjectStorageLister(Protocol):
    def __call__(
        self, prefix: str, suffix: str | None = None
    ) -> ResultE[list[str]]: ...


class ObjectStoragePresigner(Protocol):
    def __call__(self, key: str, expires_seconds: int = 3600) -> ResultE[str]: ...


class ObjectStorageProbe(Protocol):
    def __call__(self, key: str) -> ResultE[ObjectStat | None]: ...


@dataclass(frozen=True)
class ObjectStat:
    """对象存在性探测结果。"""

    key: str
    size_bytes: int
    etag: str | None
    content_type: str | None


def init_client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    addressing_style: str = "virtual",
) -> Callable[[], Minio]:
    """创建惰性 MinIO 客户端工厂；endpoint 可包含 http(s) scheme。"""
    if addressing_style not in {"path", "virtual"}:
        raise ValueError("addressing_style 必须为 'path' 或 'virtual'")
    parsed = urlsplit(endpoint if "://" in endpoint else f"https://{endpoint}")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("endpoint 必须是主机地址，可带 scheme 和端口，不可含路径")
    host = parsed.netloc
    secure = parsed.scheme == "https"
    def create_client() -> Minio:
        client = Minio(
            host,
            access_key=access_key_id,
            secret_key=secret_access_key,
            secure=secure,
            region=region_name,
        )
        if addressing_style == "virtual":
            client.enable_virtual_style_endpoint()
        else:
            client.disable_virtual_style_endpoint()
        return client

    return create_client


def init_client_from_config(config: dict) -> Callable[[], Minio]:
    """从配置构建 MinIO 客户端工厂。"""
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
    """从配置构建绑定 bucket 的 writer、reader、deleter 工厂。"""
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

    def create_workspace() -> tuple[
        ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter
    ]:
        client = init()
        return (
            bind_s3_writer(client, bucket),
            bind_s3_reader(client, bucket),
            bind_s3_deleter(client, bucket),
        )

    return create_workspace


def bind_s3_writer(client: Minio, bucket: str) -> ObjectStorageWriter:
    @safe
    def write_object(key: str, body: BinaryIO) -> None:
        # 长度未知时由 MinIO SDK 使用 multipart 上传。
        client.put_object(bucket, key, body, length=-1, part_size=10 * 1024 * 1024)

    return write_object


def bind_s3_reader(client: Minio, bucket: str) -> ObjectStorageReader:
    """返回受控消费式 reader；消费回调同步读取，响应始终关闭。"""

    @safe
    def read_object(key: str, consume: Callable[[ReadableBinaryStream], T]) -> T:
        response = client.get_object(bucket, key)
        try:
            return consume(response)
        finally:
            try:
                response.close()
            finally:
                response.release_conn()

    return read_object


def bind_s3_deleter(client: Minio, bucket: str) -> ObjectStorageDeleter:
    @safe
    def delete_object(key: str) -> None:
        client.remove_object(bucket, key)

    return delete_object


def bind_s3_presigner(client: Minio, bucket: str) -> ObjectStoragePresigner:
    """返回预签名 GET URL 生成器。"""

    @safe
    def presign(key: str, expires_seconds: int = 3600) -> str:
        if expires_seconds < 1:
            raise ValueError("expires_seconds 必须大于 0")
        from datetime import timedelta

        return client.presigned_get_object(
            bucket, key, expires=timedelta(seconds=expires_seconds)
        )

    return presign


def bind_s3_probe(client: Minio, bucket: str) -> ObjectStorageProbe:
    """对象不存在时返回 None；其他 SDK 错误由 ResultE 保留。"""

    @safe
    def probe(key: str) -> ObjectStat | None:
        try:
            stat = client.stat_object(bucket, key)
        except S3Error as error:
            if error.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return None
            raise
        if stat.size is None:
            raise ValueError("对象元数据缺少大小")
        return ObjectStat(
            key=key,
            size_bytes=stat.size,
            etag=_strip_etag(stat.etag),
            content_type=stat.content_type,
        )

    return probe


def _strip_etag(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip('"') or None


def bind_s3_lister(client: Minio, bucket: str) -> ObjectStorageLister:
    @safe
    def list_objects(prefix: str, suffix: str | None = None) -> list[str]:
        keys: list[str] = []
        for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
            key = obj.object_name
            if key is None or not key.startswith(prefix) or key.endswith("/"):
                continue
            if suffix is not None and not key.endswith(suffix):
                continue
            keys.append(key)
        return keys

    return list_objects
