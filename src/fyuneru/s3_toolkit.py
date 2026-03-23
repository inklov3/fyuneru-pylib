from collections.abc import Callable
from functools import partial
from typing import Protocol

from boto3 import Session
from botocore.config import Config
from botocore.response import StreamingBody
from mypy_boto3_s3.client import S3Client
from returns.result import ResultE, safe


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
    return partial(
        session.client,
        service_name="s3",
        endpoint_url=endpoint,
        config=config,
    )


def gen_s3writer(client: S3Client, bucket: str) -> ObjectStorageWriter:
    @safe
    def write_object(key: str, body: bytes) -> None:
        client.put_object(Bucket=bucket, Key=key, Body=body)

    return write_object


def gen_s3reader(client: S3Client, bucket: str) -> ObjectStorageReader:
    @safe
    def read_object(key: str) -> bytes:
        response = client.get_object(Bucket=bucket, Key=key)
        body: StreamingBody = response["Body"]
        byte_s: bytes = body.read()
        body.close()
        return byte_s

    return read_object


def gen_s3deleter(client: S3Client, bucket: str) -> ObjectStorageDeleter:
    @safe
    def delete_object(key: str) -> None:
        client.delete_object(Bucket=bucket, Key=key)

    return delete_object


def gen_s3lister(client: S3Client, bucket: str) -> ObjectStorageLister:
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
                key: str = obj["Key"]
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
