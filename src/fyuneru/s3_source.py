"""
S3 多源协议：通过 blob://桶id/key 统一访问多个 S3 源
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar, cast
from urllib.parse import urlparse

from loguru import logger

from fyuneru.result import Failure, ResultE, safe, unwrap
from fyuneru.s3_toolkit import (
    ObjectStorageReader,
    ReadableBinaryStream,
    bind_s3_reader,
    init_client,
)

BLOB_SCHEME = "blob"
T = TypeVar("T")


def parse_blob_uri(uri: str) -> tuple[str, str]:
    """解析 blob://桶id/key → (桶id, key)。格式错误则 raise ValueError。"""
    parsed = urlparse(uri)
    if parsed.scheme != BLOB_SCHEME:
        raise ValueError(f"不支持的协议: {parsed.scheme}，期望 {BLOB_SCHEME}")
    bucket_id = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket_id or not key:
        raise ValueError(f"URI 格式错误，桶id 和 key 不能为空: {uri}")
    return bucket_id, key


def load_source_registry(
    config: dict,
) -> dict[str, dict]:
    """从配置的 s3_sources 段加载源列表，转为以 source_id 为 key 的字典。

    检测到重复 source_id 时打印警告，后续配置覆盖前面的。
    """
    sources = config["s3_sources"]
    if not isinstance(sources, list):
        raise ValueError("s3_sources 必须是列表")

    required_fields = (
        "source_id",
        "endpoint",
        "bucket",
        "access_key_id",
        "secret_access_key",
    )
    registry: dict[str, dict] = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"s3_sources[{index}] 必须是对象")
        missing_fields = [field for field in required_fields if field not in source]
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise ValueError(f"s3_sources[{index}] 缺少字段: {joined}")

        source_id = source["source_id"]
        if not isinstance(source_id, str) or source_id == "":
            raise ValueError(f"s3_sources[{index}] 的 source_id 必须是非空字符串")

        if source_id in registry:
            logger.warning(f"检测到重复的 source_id: {source_id}，后续配置将覆盖前面的")
        registry[source_id] = source
    return registry


def lookup_source(registry: dict[str, dict], bucket_id: str) -> dict:
    """按 bucket_id 查注册表，未注册时抛 KeyError。"""
    if bucket_id not in registry:
        raise KeyError(f"unsupport bucket id: {bucket_id}")
    return registry[bucket_id]


def build_reader_for(source_cfg: dict) -> ObjectStorageReader:
    """按单条 source 配置初始化 client 并绑定 reader。"""
    client = init_client(
        endpoint=source_cfg["endpoint"],
        access_key_id=source_cfg["access_key_id"],
        secret_access_key=source_cfg["secret_access_key"],
        region_name=source_cfg.get("region_name"),
        addressing_style=source_cfg.get("addressing_style", "virtual"),
    )()
    return bind_s3_reader(client, source_cfg["bucket"])


@dataclass
class MultiSourceReader:
    """按 bucket_id 缓存 reader 的多源容器。

    第一次访问某个 bucket_id 时懒初始化 client + reader，之后命中缓存。
    """

    registry: dict[str, dict]
    _readers: dict[str, ObjectStorageReader] = field(default_factory=dict)

    def reader_for(self, bucket_id: str) -> ObjectStorageReader:
        if bucket_id not in self._readers:
            source_cfg = lookup_source(self.registry, bucket_id)
            self._readers[bucket_id] = build_reader_for(source_cfg)
        return self._readers[bucket_id]

    def read(
        self,
        uri: str,
        consume: Callable[[ReadableBinaryStream], T],
    ) -> ResultE[T]:
        parsed_result = _safe_parse_uri(uri)
        if isinstance(parsed_result, Failure):
            return parsed_result

        bucket_id, key = unwrap(parsed_result)
        reader_result = _safe_reader_for(self, bucket_id)
        if isinstance(reader_result, Failure):
            return reader_result

        reader = unwrap(reader_result)
        return reader(key, consume)


@safe
def _safe_parse_uri(uri: str) -> tuple[str, str]:
    return parse_blob_uri(uri)


@safe
def _safe_reader_for(
    multi_reader: MultiSourceReader, bucket_id: str
) -> ObjectStorageReader:
    return multi_reader.reader_for(bucket_id)


def bind_source_reader(
    registry: dict[str, dict],
) -> ObjectStorageReader:
    """返回一个受控消费式 blob:// URI reader。

    内部按需懒初始化 client + reader，缓存已创建的实例。
    """
    multi_reader = MultiSourceReader(registry=registry)
    return cast(ObjectStorageReader, multi_reader.read)
