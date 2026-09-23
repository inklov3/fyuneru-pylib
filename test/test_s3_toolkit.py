"""测试 s3_toolkit 新增的预签名与对象探测绑定。"""

from botocore.exceptions import ClientError

from fyuneru.result import Failure, is_failure, is_success, unwrap
from fyuneru.s3_toolkit import bind_s3_presigner, bind_s3_probe


class FakeS3Client:
    def __init__(
        self,
        head_response: dict | None = None,
        head_error: Exception | None = None,
        presign_error: Exception | None = None,
    ):
        self.head_response = head_response
        self.head_error = head_error
        self.presign_error = presign_error
        self.presign_kwargs: dict | None = None
        self.head_kwargs: dict | None = None

    def generate_presigned_url(self, **kwargs) -> str:
        self.presign_kwargs = kwargs
        if self.presign_error is not None:
            raise self.presign_error
        params = kwargs["Params"]
        return (
            f"https://s3.example.com/{params['Bucket']}/{params['Key']}"
            f"?X-Amz-Expires={kwargs['ExpiresIn']}"
        )

    def head_object(self, **kwargs) -> dict:
        self.head_kwargs = kwargs
        if self.head_error is not None:
            raise self.head_error
        assert self.head_response is not None
        return self.head_response


def _client_error(status: int, code: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "HeadObject",
    )


def test_presign_builds_get_url() -> None:
    client = FakeS3Client()
    presign = bind_s3_presigner(client, "my-bucket")  # type: ignore[arg-type]
    result = presign("prepared/a.mp4", expires_seconds=900)
    assert is_success(result)
    assert unwrap(result).endswith("X-Amz-Expires=900")
    assert client.presign_kwargs is not None
    assert client.presign_kwargs["ClientMethod"] == "get_object"
    assert client.presign_kwargs["Params"] == {
        "Bucket": "my-bucket",
        "Key": "prepared/a.mp4",
    }


def test_presign_rejects_non_positive_expiry() -> None:
    presign = bind_s3_presigner(FakeS3Client(), "b")  # type: ignore[arg-type]
    result = presign("k", expires_seconds=0)
    assert is_failure(result), "非正有效期必须返回 Failure"


def test_presign_propagates_client_failure() -> None:
    client = FakeS3Client(presign_error=RuntimeError("signer down"))
    presign = bind_s3_presigner(client, "b")  # type: ignore[arg-type]
    assert is_failure(presign("k"))


def test_probe_returns_stat_for_existing_object() -> None:
    client = FakeS3Client(
        head_response={
            "ContentLength": 1234,
            "ETag": '"abc123"',
            "ContentType": "video/mp4",
        }
    )
    probe = bind_s3_probe(client, "my-bucket")  # type: ignore[arg-type]
    result = probe("prepared/a.mp4")
    assert is_success(result)
    stat = unwrap(result)
    assert stat is not None
    assert stat.size_bytes == 1234
    assert stat.etag == "abc123", "ETag 引号必须剥掉"
    assert stat.content_type == "video/mp4"


def test_probe_maps_missing_object_to_none() -> None:
    for error in (
        _client_error(404, "404"),
        _client_error(404, "NoSuchKey"),
        _client_error(403, "NotFound"),
    ):
        probe = bind_s3_probe(FakeS3Client(head_error=error), "b")  # type: ignore[arg-type]
        result = probe("k")
        assert is_success(result), f"缺失对象不应是错误: {error}"
        assert unwrap(result) is None


def test_probe_propagates_other_client_errors() -> None:
    probe = bind_s3_probe(
        FakeS3Client(head_error=_client_error(403, "AccessDenied")),  # type: ignore[arg-type]
        "b",
    )
    result = probe("k")
    assert is_failure(result), "鉴权失败不得被当成对象不存在"
    assert isinstance(result, Failure)
    assert isinstance(result.error, ClientError)


def main() -> None:
    test_presign_builds_get_url()
    test_presign_rejects_non_positive_expiry()
    test_presign_propagates_client_failure()
    test_probe_returns_stat_for_existing_object()
    test_probe_maps_missing_object_to_none()
    test_probe_propagates_other_client_errors()
    print("test_s3_toolkit: 全部通过")


if __name__ == "__main__":
    main()
