"""
S3 多源协议：通过 blob://桶id/key 统一访问多个 S3 源
"""

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from returns.result import ResultE, safe

from fyuneru.config import read_config
from fyuneru.s3_toolkit import ObjectStorageReader, gen_s3worker, init_client

BLOB_SCHEME = "blob"


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


def load_source_registry(config_path: Path) -> dict[str, dict]:
    """从配置文件的 s3_sources 段加载源列表，转为以 source_id 为 key 的字典。"""
    config = read_config(config_path)
    sources = config["s3_sources"]
    registry: dict[str, dict] = {}
    for source in sources:
        source_id = source["source_id"]
        if source_id in registry:
            raise ValueError(f"重复的 source_id: {source_id}")
        registry[source_id] = source
    return registry


def init_source_reader(
    registry: dict[str, dict],
) -> Callable[[str], ResultE[bytes]]:
    """返回一个闭包函数，接受 blob:// URI，返回 ResultE[bytes]。
    内部按需懒初始化 client + reader，缓存已创建的实例。"""
    readers: dict[str, ObjectStorageReader] = {}

    @safe
    def read(uri: str) -> bytes:
        bucket_id, key = parse_blob_uri(uri)
        if bucket_id not in registry:
            raise KeyError(f"unsupport bucket id: {bucket_id}")
        if bucket_id not in readers:
            cfg = registry[bucket_id]
            client = init_client(
                endpoint=cfg["endpoint"],
                access_key_id=cfg["access_key_id"],
                secret_access_key=cfg["secret_access_key"],
                region_name=cfg.get("region_name"),
            )()  # 调用 partial 得到实际 client
            _, reader, _ = gen_s3worker(client, cfg["bucket"])
            readers[bucket_id] = reader
        return readers[bucket_id](key).unwrap()

    return read
