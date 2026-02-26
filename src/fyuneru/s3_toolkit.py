from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from boto3 import Session
from botocore.config import Config
from botocore.response import StreamingBody
from mypy_boto3_s3.client import S3Client
from returns.result import safe


class ObjectStorageWriter(Protocol):
    @safe
    def __call__(self, key: str, body: bytes) -> None: ...


class ObjectStorageReader(Protocol):
    @safe
    def __call__(self, key: str) -> bytes: ...


class ObjectStorageDeleter(Protocol):
    @safe
    def __call__(self, key: str) -> None: ...


def create_s3client(
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str | None = None,
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
) -> S3Client:
    session: Session = Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
    )
    return session.client(
        service_name="s3",
        endpoint_url=endpoint,
        config=config,
    )


def init_s3worker(
    client: S3Client, bucket: str
) -> tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]:
    client: S3Client = client

    @safe
    def write_object(key: str, body: bytes) -> None:
        client.put_object(Bucket=bucket, Key=key, Body=body)

    @safe
    def read_object(key: str) -> bytes:
        response = client.get_object(Bucket=bucket, Key=key)
        body: StreamingBody = response["Body"]
        byte_s: bytes = body.read()
        body.close()
        return byte_s

    @safe
    def delete_object(key: str) -> None:
        client.delete_object(Bucket=bucket, Key=key)

    return write_object, read_object, delete_object


@dataclass(frozen=True)
class BucketSource:
    """
    多s3源支持, 桶单位
    """

    id: str
    endpoint: str
    region: str
    access_key_id: str
    secret_access_key: str
    bucket: str
