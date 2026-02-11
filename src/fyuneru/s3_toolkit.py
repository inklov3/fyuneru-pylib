from collections.abc import Callable
from functools import partial
from typing import Protocol

from boto3.session import Session
from botocore.config import Config
from botocore.response import StreamingBody
from mypy_boto3_s3.client import S3Client
from returns.result import safe


def create_session(
    access_key_id: str,
    secret_access_key: str,
    region_name: str = "us-east-1",
) -> Session:
    return Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
    )


def init_s3_client(
    session: Session,
    endpoint: str,
    service_name: str = "s3",
    config: Config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
) -> Callable[[], S3Client]:
    return partial(
        session.client,
        service_name=service_name,
        endpoint_url=endpoint,
        config=config,
    )


class ObjectStorageWriter(Protocol):
    @safe
    def __call__(self, key: str, body: bytes) -> None: ...


class ObjectStorageReader(Protocol):
    @safe
    def __call__(self, key: str) -> bytes: ...


class ObjectStorageDeleter(Protocol):
    @safe
    def __call__(self, key: str) -> None: ...


def init_s3(
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
