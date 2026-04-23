from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from boto3 import Session
from botocore.config import Config
from botocore.response import StreamingBody

from fyuneru.result import ResultE, safe

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


class ObjectStorageWriter(Protocol):
    def __call__(self, key: str, body: bytes) -> ResultE[None]: ...


class ObjectStorageReader(Protocol):
    def __call__(self, key: str) -> ResultE[bytes]: ...


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
) -> Callable[[], S3Client]:
    if config is None:
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
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
    s3_cfg = config["s3"]
    return init_client(
        endpoint=s3_cfg["endpoint"],
        access_key_id=s3_cfg["access_key_id"],
        secret_access_key=s3_cfg["secret_access_key"],
        region_name=s3_cfg.get("region_name"),
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
    s3_cfg = config["s3"]
    init = init_client(
        endpoint=s3_cfg["endpoint"],
        access_key_id=s3_cfg["access_key_id"],
        secret_access_key=s3_cfg["secret_access_key"],
        region_name=s3_cfg.get("region_name"),
    )
    bucket = s3_cfg["bucket"]

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
    @safe
    def read_object(key: str) -> bytes:
        response = client.get_object(Bucket=bucket, Key=key)
        body: StreamingBody = response["Body"]
        byte_s: bytes = body.read()
        body.close()
        return byte_s

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
            continuation_token = response["NextContinuationToken"]
        return keys

    return list_objects
