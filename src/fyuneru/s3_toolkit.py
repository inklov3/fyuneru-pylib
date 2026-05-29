from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol, TypeVar, cast, overload

from boto3 import Session
from botocore.config import Config

from fyuneru.config import parse_s3_config
from fyuneru.result import ResultE, safe

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

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
        self,
        key: str,
        consume: Callable[[ReadableBinaryStream], T],
    ) -> ResultE[T]: ...


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
    def write_object(key: str, body: BinaryIO) -> None:
        client.upload_fileobj(body, bucket, key)

    return write_object


def bind_s3_reader(client: S3Client, bucket: str) -> ObjectStorageReader:
    """返回受控消费式对象 reader，消费函数必须同步读取流。"""

    @safe
    def read_object(
        key: str,
        consume: Callable[[ReadableBinaryStream], T],
    ) -> T:
        response = client.get_object(Bucket=bucket, Key=key)
        body = cast(ReadableBinaryStream, response["Body"])
        try:
            return consume(body)
        finally:
            body.close()

    return read_object


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
