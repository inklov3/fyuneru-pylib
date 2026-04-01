"""测试 s3_source 模块的 URI 解析功能"""

from pathlib import Path
from tempfile import TemporaryDirectory

from fyuneru.config import read_config_with_override
from fyuneru.s3_source import load_source_registry, parse_blob_uri


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


if __name__ == "__main__":
    test_parse_blob_uri_normal()
    test_parse_blob_uri_simple_key()
    test_parse_blob_uri_wrong_scheme()
    test_parse_blob_uri_empty_bucket()
    test_parse_blob_uri_empty_key()
    test_parse_blob_uri_no_key()
    test_load_source_registry_with_override()
    print("所有 parse_blob_uri 测试通过")
