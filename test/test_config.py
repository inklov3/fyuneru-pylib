"""测试 config 模块的增量覆盖能力。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from fyuneru.config import (
    parse_mongo_config,
    parse_redis_config,
    parse_s3_config,
    read_config,
    read_config_from_paths,
)


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_read_config_with_override_merge_rules():
    with TemporaryDirectory() as tmp:
        base_path = Path(tmp) / "base.yml"
        pod_path = Path(tmp) / "pod.yml"

        _write_yaml(
            base_path,
            """
redis:
  host: base-host
  port: 6379
  db: 0

service:
  retries: 3
  labels:
  - core
  - stable
  nested:
    timeout: 1000
    mode: strict

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
        )

        _write_yaml(
            pod_path,
            """
redis:
  host: pod-host

service:
  labels:
  - pod
  nested:
    mode: relaxed
    worker: pod-a

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
        )

        merged = read_config_from_paths([base_path, pod_path])
        assert merged["redis"]["host"] == "pod-host"
        assert merged["redis"]["port"] == 6379
        assert merged["service"]["retries"] == 3
        assert merged["service"]["nested"]["timeout"] == 1000
        assert merged["service"]["nested"]["mode"] == "relaxed"
        assert merged["service"]["nested"]["worker"] == "pod-a"
        assert merged["service"]["labels"] == ["core", "stable", "pod"]

        s3_sources = merged["s3_sources"]
        assert len(s3_sources) == 4  # 直接拼接，不去重
        by_id = {source["source_id"]: source for source in s3_sources}
        assert by_id["my-images"]["bucket"] == "pod-bucket"
        assert by_id["archive"]["bucket"] == "archive-bucket"
        assert by_id["backup"]["bucket"] == "backup-bucket"


def test_read_config_with_override_none_equals_read_config():
    with TemporaryDirectory() as tmp:
        base_path = Path(tmp) / "base.yml"
        _write_yaml(
            base_path,
            """
llm:
  provider: gemini
  api_key: base-key
  endpoint: https://api.example.com
""",
        )

        assert read_config_from_paths([base_path]) == read_config(base_path)


def test_parse_redis_config_success() -> None:
    parsed = parse_redis_config(
        {
            "redis": {
                "host": "127.0.0.1",
                "port": 6379,
                "db": 1,
                "password": "secret",
                "cluster": False,
            }
        }
    )
    assert parsed.host == "127.0.0.1"
    assert parsed.port == 6379
    assert parsed.db == 1
    assert parsed.password == "secret"
    assert parsed.cluster is False


def test_parse_s3_config_success() -> None:
    parsed = parse_s3_config(
        {
            "s3": {
                "endpoint": "https://s3.example.com",
                "access_key_id": "ak",
                "secret_access_key": "sk",
                "bucket": "bucket-a",
                "region_name": "us-east-1",
                "addressing_style": "path",
            }
        }
    )
    assert parsed.endpoint == "https://s3.example.com"
    assert parsed.bucket == "bucket-a"
    assert parsed.region_name == "us-east-1"
    assert parsed.addressing_style == "path"


def test_parse_s3_config_rejects_invalid_addressing_style() -> None:
    try:
        parse_s3_config(
            {
                "s3": {
                    "endpoint": "https://s3.example.com",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                    "addressing_style": "invalid",
                }
            }
        )
        assert False, "应抛出 ValueError"
    except ValueError as error:
        assert "addressing_style" in str(error)


def test_parse_mongo_config_success() -> None:
    parsed = parse_mongo_config(
        {
            "mongo": {
                "uri": "mongodb://127.0.0.1:27017",
                "db": "mydb",
                "timeout": 5000,
            }
        }
    )
    assert parsed.uri == "mongodb://127.0.0.1:27017"
    assert parsed.db == "mydb"
    assert parsed.timeout == 5000


if __name__ == "__main__":
    test_read_config_with_override_merge_rules()
    test_read_config_with_override_none_equals_read_config()
    test_parse_redis_config_success()
    test_parse_s3_config_success()
    test_parse_s3_config_rejects_invalid_addressing_style()
    test_parse_mongo_config_success()
    print("所有 config 覆盖测试通过")
