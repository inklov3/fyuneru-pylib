"""测试 s3_source 模块的 URI 解析功能"""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import fyuneru.s3_source as s3_source_module
from fyuneru.config import read_config_with_override
from fyuneru.result import Failure, Success, is_failure, unwrap
from fyuneru.s3_source import bind_source_reader, load_source_registry, parse_blob_uri
from fyuneru.s3_toolkit import bind_s3_reader, bind_s3_writer


class FakeBody:
    def __init__(self, data: bytes = b"", fail_on_read: Exception | None = None):
        self._stream = BytesIO(data)
        self._fail_on_read = fail_on_read
        self.closed = False
        self.released = False

    def read(self, amt: int | None = None) -> bytes:
        if self._fail_on_read is not None:
            raise self._fail_on_read
        if amt is None:
            return self._stream.read()
        return self._stream.read(amt)

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeS3Client:
    def __init__(
        self,
        body: FakeBody | None = None,
        get_error: Exception | None = None,
    ):
        self.body = body
        self.get_error = get_error
        self.get_object_kwargs: dict | None = None
        self.uploaded: tuple[str, str, bytes] | None = None
        self.put_args: tuple | None = None

    def get_object(self, bucket: str, key: str):
        self.get_object_kwargs = {"Bucket": bucket, "Key": key}
        if self.get_error is not None:
            raise self.get_error
        return self.body

    def put_object(self, bucket, key, body, length, part_size):
        self.put_args = (bucket, key, length, part_size)
        self.uploaded = (bucket, key, body.read())


class BrokenFile:
    def read(self) -> bytes:
        raise OSError("read failed")


def test_parse_blob_uri_normal():
    bucket_id, key = parse_blob_uri("blob://my-images/photos/2024/img001.jpg")
    assert bucket_id == "my-images", f"期望 'my-images'，得到 '{bucket_id}'"
    assert key == "photos/2024/img001.jpg", (
        f"期望 'photos/2024/img001.jpg'，得到 '{key}'"
    )


def test_parse_blob_uri_simple_key():
    bucket_id, key = parse_blob_uri("blob://backup/file.bin")
    assert bucket_id == "backup"
    assert key == "file.bin"


def test_parse_blob_uri_wrong_scheme():
    try:
        parse_blob_uri("s3://bucket/key")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不支持的协议" in str(e)


def test_parse_blob_uri_empty_bucket():
    try:
        parse_blob_uri("blob:///key")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不能为空" in str(e)


def test_parse_blob_uri_empty_key():
    try:
        parse_blob_uri("blob://bucket/")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不能为空" in str(e)


def test_parse_blob_uri_no_key():
    try:
        parse_blob_uri("blob://bucket")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不能为空" in str(e)


def test_load_source_registry_with_override():
    with TemporaryDirectory() as tmp:
        base_path = Path(tmp) / "base.yml"
        override_path = Path(tmp) / "pod.yml"

        base_path.write_text(
            """
s3_sources:
- source_id: my-images
  endpoint: https://base-s3.example.com
  bucket: base-bucket
  access_key_id: base-ak
  secret_access_key: base-sk

- source_id: archive
  endpoint: https://archive.example.com
  bucket: archive-bucket
  access_key_id: archive-ak
  secret_access_key: archive-sk
""",
            encoding="utf-8",
        )

        override_path.write_text(
            """
s3_sources:
- source_id: my-images
  endpoint: https://pod-s3.example.com
  bucket: pod-bucket
  access_key_id: pod-ak
  secret_access_key: pod-sk

- source_id: backup
  endpoint: https://backup.example.com
  bucket: backup-bucket
  access_key_id: backup-ak
  secret_access_key: backup-sk
""",
            encoding="utf-8",
        )

        config = read_config_with_override(base_path, override_path)
        registry = load_source_registry(config)
        assert set(registry.keys()) == {"my-images", "archive", "backup"}
        assert registry["my-images"]["bucket"] == "pod-bucket"
        assert registry["archive"]["bucket"] == "archive-bucket"
        assert registry["backup"]["bucket"] == "backup-bucket"


def test_load_source_registry_validate_required_fields():
    try:
        load_source_registry(
            {
                "s3_sources": [
                    {
                        "source_id": "my-images",
                        "endpoint": "https://s3.example.com",
                        "bucket": "my-bucket",
                        "access_key_id": "ak",
                    }
                ]
            }
        )
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "缺少字段" in str(e)


def test_bind_s3_reader_consumes_and_closes_body():
    body = FakeBody(b"source-data")
    client = FakeS3Client(body=body)
    read = bind_s3_reader(client, "bucket-a")

    result = read("path.txt", lambda stream: stream.read())

    assert unwrap(result) == b"source-data"
    assert body.closed
    assert body.released
    assert client.get_object_kwargs == {"Bucket": "bucket-a", "Key": "path.txt"}


def test_bind_s3_reader_wraps_get_object_error():
    client = FakeS3Client(get_error=RuntimeError("get failed"))
    read = bind_s3_reader(client, "bucket-a")

    result = read("path.txt", lambda stream: stream.read())

    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "get failed" in str(result.error)


def test_bind_s3_reader_wraps_body_read_error_and_closes_body():
    body = FakeBody(fail_on_read=OSError("network failed"))
    client = FakeS3Client(body=body)
    read = bind_s3_reader(client, "bucket-a")

    result = read("path.txt", lambda stream: stream.read())

    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "network failed" in str(result.error)
    assert body.closed
    assert body.released


def test_bind_s3_reader_wraps_consumer_error_and_closes_body():
    body = FakeBody(b"source-data")
    client = FakeS3Client(body=body)
    read = bind_s3_reader(client, "bucket-a")

    def consume(_stream):
        raise ValueError("consume failed")

    result = read("path.txt", consume)

    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "consume failed" in str(result.error)
    assert body.closed
    assert body.released


def test_bind_s3_writer_uploads_unknown_length_stream():
    client = FakeS3Client()
    write = bind_s3_writer(client, "bucket-a")

    unwrap(write("path.txt", BytesIO(b"payload")))

    assert client.uploaded == ("bucket-a", "path.txt", b"payload")
    assert client.put_args == ("bucket-a", "path.txt", -1, 10 * 1024 * 1024)


def test_bind_s3_writer_wraps_body_read_error():

    client = FakeS3Client()
    write = bind_s3_writer(client, "bucket-a")

    result = write("path.txt", BrokenFile())  # type: ignore[arg-type]

    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "read failed" in str(result.error)


def _assert_build_reader_addressing_style(source_cfg: dict, expected_style: str):
    with patch.object(
        s3_source_module, "init_client", return_value=lambda: FakeS3Client()
    ) as mock_init_client:
        s3_source_module.build_reader_for(source_cfg)

    mock_init_client.assert_called_once_with(
        endpoint="https://s3.example.com",
        access_key_id="ak",
        secret_access_key="sk",
        region_name=None,
        addressing_style=expected_style,
    )


def test_build_reader_for_path_addressing_style():
    _assert_build_reader_addressing_style(
        {
            "endpoint": "https://s3.example.com",
            "bucket": "bucket-a",
            "access_key_id": "ak",
            "secret_access_key": "sk",
            "addressing_style": "path",
        },
        "path",
    )


def test_build_reader_for_virtual_addressing_style():
    _assert_build_reader_addressing_style(
        {
            "endpoint": "https://s3.example.com",
            "bucket": "bucket-a",
            "access_key_id": "ak",
            "secret_access_key": "sk",
            "addressing_style": "virtual",
        },
        "virtual",
    )


def test_build_reader_for_defaults_to_virtual_addressing_style():
    _assert_build_reader_addressing_style(
        {
            "endpoint": "https://s3.example.com",
            "bucket": "bucket-a",
            "access_key_id": "ak",
            "secret_access_key": "sk",
        },
        "virtual",
    )


def test_bind_source_reader_with_unknown_bucket():
    read = bind_source_reader(
        {
            "known": {
                "source_id": "known",
                "endpoint": "https://s3.example.com",
                "bucket": "known-bucket",
                "access_key_id": "ak",
                "secret_access_key": "sk",
            }
        }
    )
    result = read("blob://unknown/path.txt", lambda body: body.read())
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "unsupport bucket id" in str(result.error)


def test_bind_source_reader_consumes_stream():
    original_build_reader_for = s3_source_module.build_reader_for
    called: dict[str, str] = {}

    def fake_build_reader_for(_source_cfg: dict):
        def fake_reader(key, consume):

            called["key"] = key
            return Success(consume(BytesIO(b"source-data")))

        return fake_reader

    try:
        s3_source_module.build_reader_for = fake_build_reader_for  # type: ignore[assignment]
        read = bind_source_reader(
            {
                "known": {
                    "source_id": "known",
                    "endpoint": "https://s3.example.com",
                    "bucket": "known-bucket",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                }
            }
        )
        assert (
            unwrap(read("blob://known/path.txt", lambda body: body.read()))
            == b"source-data"
        )
        assert called["key"] == "path.txt"
    finally:
        s3_source_module.build_reader_for = original_build_reader_for


if __name__ == "__main__":
    test_parse_blob_uri_normal()
    test_parse_blob_uri_simple_key()
    test_parse_blob_uri_wrong_scheme()
    test_parse_blob_uri_empty_bucket()
    test_parse_blob_uri_empty_key()
    test_parse_blob_uri_no_key()
    test_load_source_registry_with_override()
    test_load_source_registry_validate_required_fields()
    test_bind_s3_reader_consumes_and_closes_body()
    test_bind_s3_reader_wraps_get_object_error()
    test_bind_s3_reader_wraps_body_read_error_and_closes_body()
    test_bind_s3_reader_wraps_consumer_error_and_closes_body()
    test_bind_s3_writer_uploads_unknown_length_stream()
    test_bind_s3_writer_wraps_body_read_error()
    test_build_reader_for_path_addressing_style()
    test_build_reader_for_virtual_addressing_style()
    test_build_reader_for_defaults_to_virtual_addressing_style()
    test_bind_source_reader_with_unknown_bucket()
    test_bind_source_reader_consumes_stream()
    print("所有 s3_source 测试通过")
