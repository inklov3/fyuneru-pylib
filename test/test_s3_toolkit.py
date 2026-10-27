"""测试 s3_toolkit 的 MinIO 绑定。"""

from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

from urllib3.response import HTTPResponse

from fyuneru.result import Failure, is_failure, is_success, unwrap
from fyuneru.s3_toolkit import (
    S3Error,
    bind_s3_lister,
    bind_s3_presigner,
    bind_s3_probe,
    init_client,
)


class FakeS3Client:
    def __init__(
        self, stat_response=None, stat_error=None, presign_error=None, objects=()
    ):
        self.stat_response = stat_response
        self.stat_error = stat_error
        self.presign_error = presign_error
        self.objects = objects
        self.presign_args = None
        self.stat_args = None
        self.list_args = None

    def presigned_get_object(self, bucket, key, expires):
        self.presign_args = (bucket, key, expires)
        if self.presign_error is not None:
            raise self.presign_error
        return f"https://s3.example.com/{bucket}/{key}"

    def stat_object(self, bucket, key):
        self.stat_args = (bucket, key)
        if self.stat_error is not None:
            raise self.stat_error
        return self.stat_response

    def list_objects(self, bucket, prefix, recursive):
        self.list_args = (bucket, prefix, recursive)
        return iter(self.objects)


def _s3_error(code: str) -> S3Error:
    return S3Error(HTTPResponse(), code, "boom", "resource", "request", "host")


def test_real_client_addressing_and_endpoint_validation() -> None:
    for style, expected_host, expected_path in (
        ("path", "example.com:9000", "/test-bucket/key"),
        ("virtual", "test-bucket.example.com:9000", "/key"),
    ):
        client = init_client(
            "http://example.com:9000",
            "access",
            "secret",
            region_name="us-east-1",
            addressing_style=style,
        )()
        url = urlsplit(unwrap(bind_s3_presigner(client, "test-bucket")("key")))
        assert (url.scheme, url.netloc, url.path) == (
            "http",
            expected_host,
            expected_path,
        )
    for endpoint in (
        "ftp://example.com",
        "https://example.com/path",
        "https://u:p@example.com",
    ):
        try:
            init_client(endpoint, "access", "secret")
        except ValueError:
            continue
        raise AssertionError(f"不应接受 endpoint: {endpoint}")


def test_presign_builds_get_url() -> None:
    client = FakeS3Client()
    result = bind_s3_presigner(client, "my-bucket")("prepared/a.mp4", 900)  # type: ignore[arg-type]
    assert is_success(result)
    assert unwrap(result).endswith("a.mp4")
    assert client.presign_args == (
        "my-bucket",
        "prepared/a.mp4",
        timedelta(seconds=900),
    )


def test_presign_rejects_non_positive_expiry() -> None:
    result = bind_s3_presigner(FakeS3Client(), "b")("k", 0)  # type: ignore[arg-type]
    assert is_failure(result)


def test_presign_propagates_client_failure() -> None:
    result = bind_s3_presigner(
        FakeS3Client(presign_error=RuntimeError("signer down")),  # type: ignore[arg-type]
        "b",
    )("k")
    assert is_failure(result)


def test_probe_returns_stat_for_existing_object() -> None:
    client = FakeS3Client(
        stat_response=SimpleNamespace(
            size=1234, etag='"abc123"', content_type="video/mp4"
        )
    )
    result = bind_s3_probe(client, "my-bucket")("prepared/a.mp4")  # type: ignore[arg-type]
    assert is_success(result)
    stat = unwrap(result)
    assert stat is not None
    assert (stat.key, stat.size_bytes, stat.etag, stat.content_type) == (
        "prepared/a.mp4",
        1234,
        "abc123",
        "video/mp4",
    )
    assert client.stat_args == ("my-bucket", "prepared/a.mp4")


def test_probe_maps_missing_object_to_none() -> None:
    for code in ("NoSuchKey", "NoSuchObject", "NotFound"):
        result = bind_s3_probe(FakeS3Client(stat_error=_s3_error(code)), "b")("k")  # type: ignore[arg-type]
        assert is_success(result), f"缺失对象不应是错误: {code}"
        assert unwrap(result) is None


def test_probe_propagates_other_client_errors() -> None:
    result = bind_s3_probe(FakeS3Client(stat_error=_s3_error("AccessDenied")), "b")("k")  # type: ignore[arg-type]
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert isinstance(result.error, S3Error)


def test_lister_recursively_filters_suffix_and_directories() -> None:
    objects = [
        SimpleNamespace(object_name="prefix/a.mp4"),
        SimpleNamespace(object_name="prefix/b.txt"),
        SimpleNamespace(object_name="prefix/folder/"),
        SimpleNamespace(object_name=None),
        SimpleNamespace(object_name="other/c.mp4"),
    ]
    client = FakeS3Client(objects=objects)
    result = bind_s3_lister(client, "b")("prefix/", suffix=".mp4")  # type: ignore[arg-type]
    assert unwrap(result) == ["prefix/a.mp4"]
    assert client.list_args == ("b", "prefix/", True)


def main() -> None:
    test_real_client_addressing_and_endpoint_validation()
    test_presign_builds_get_url()
    test_presign_rejects_non_positive_expiry()
    test_presign_propagates_client_failure()
    test_probe_returns_stat_for_existing_object()
    test_probe_maps_missing_object_to_none()
    test_probe_propagates_other_client_errors()
    test_lister_recursively_filters_suffix_and_directories()
    print("test_s3_toolkit: 全部通过")


if __name__ == "__main__":
    main()
