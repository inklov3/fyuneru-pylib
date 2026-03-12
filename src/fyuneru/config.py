"""
配置构建器
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yaml import safe_load

if TYPE_CHECKING:
    from google.genai import Client
    from mypy_boto3_s3.client import S3Client
    from pymongo import MongoClient
    from pymongo.database import Database
    from redis import Redis, RedisCluster

    from fyuneru.s3_toolkit import (
        ObjectStorageDeleter,
        ObjectStorageReader,
        ObjectStorageWriter,
    )


def _read_yaml_mapping(config: Path) -> dict[str, Any]:
    suffix = config.suffix
    if suffix not in (".yaml", ".yml"):
        raise ValueError(f"不支持的配置文件格式: {suffix}")
    loaded = safe_load(config.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("配置文件根节点必须是对象映射")
    return loaded


def read_config(config: Path) -> dict[str, list | dict]:
    return _read_yaml_mapping(config)


def _merge_s3_sources(sources: list[Any]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("s3_sources 的每个条目都必须是对象")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("s3_sources.source_id 必须是非空字符串")
        deduped[source_id] = source
    return list(deduped.values())


def _merge_config_value(base: Any, override: Any, path: tuple[str, ...]) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, override_value in override.items():
            key_name = str(key)
            next_path = (*path, key_name)
            if key in merged:
                merged[key] = _merge_config_value(merged[key], override_value, next_path)
            else:
                merged[key] = _merge_config_value(None, override_value, next_path)
        return merged

    if isinstance(override, list) and path and path[-1] == "s3_sources":
        if isinstance(base, list):
            return _merge_s3_sources([*base, *override])
        return _merge_s3_sources([*override])

    if isinstance(base, list) and isinstance(override, list):
        return [*base, *override]

    return override


def read_config_with_override(
    base: Path,
    override: Path | None = None,
) -> dict[str, Any]:
    """读取 base 配置，并可选叠加一层 override 配置。"""
    base_config = _read_yaml_mapping(base)
    if override is None:
        return base_config
    override_config = _read_yaml_mapping(override)
    merged = _merge_config_value(base_config, override_config, ())
    if not isinstance(merged, dict):
        raise ValueError("合并后的配置根节点必须是对象映射")
    return merged


# ---------------------------------------------------------------------------
# 底层 client initializer — 返回裸客户端工厂，与各 toolkit 的 init_* 对齐
# ---------------------------------------------------------------------------


def init_redis_from_config(
    config: dict,
) -> Callable[[], "Redis"] | Callable[[], "RedisCluster"]:
    """从 'redis' 段构建 redis client initializer。

    返回 Callable[[], Redis] 或 Callable[[], RedisCluster]。
    """
    from fyuneru import redis_toolkit

    redis_cfg = config["redis"]
    extra: dict = {}
    if "password" in redis_cfg:
        extra["password"] = redis_cfg["password"]
    if redis_cfg.get("cluster", False):
        return redis_toolkit.init_client_cluster(
            host=redis_cfg["host"], port=redis_cfg["port"], **extra
        )
    return redis_toolkit.init_client_standalone(
        host=redis_cfg["host"],
        port=redis_cfg["port"],
        db=redis_cfg.get("db", 0),
        **extra,
    )


def init_s3_from_config(config: dict) -> Callable[[], "S3Client"]:
    """从 's3' 段构建 s3 client initializer。"""
    from fyuneru import s3_toolkit

    s3_cfg = config["s3"]
    return s3_toolkit.init_client(
        endpoint=s3_cfg["endpoint"],
        access_key_id=s3_cfg["access_key_id"],
        secret_access_key=s3_cfg["secret_access_key"],
        region_name=s3_cfg.get("region_name"),
    )


def init_mongo_from_config(config: dict) -> Callable[[], "MongoClient"]:
    """从 'mongo' 段构建 mongo client initializer。"""
    from fyuneru import mongo_toolkit

    mongo_cfg = config["mongo"]
    kwargs: dict = {"uri": mongo_cfg["uri"]}
    if "timeout" in mongo_cfg:
        kwargs["timeout"] = mongo_cfg["timeout"]
    return mongo_toolkit.init_client(**kwargs)


def init_llm_from_config(config: dict) -> Callable[[], "Client"]:
    """从 'llm' 段构建 LLM client initializer。目前支持 gemini。"""
    llm_cfg = config["llm"]
    provider = llm_cfg["provider"]
    if provider == "gemini":
        from fyuneru import gemini_toolkit

        return gemini_toolkit.init_client(
            api_key=llm_cfg["api_key"],
            endpoint=llm_cfg["endpoint"],
            api_version=llm_cfg.get("api_version", "v1beta"),
        )
    raise ValueError(f"不支持的 LLM provider: {provider}")


# ---------------------------------------------------------------------------
# 高层 workspace initializer — 绑定配置中的资源名称，返回可直接使用的对象工厂
# ---------------------------------------------------------------------------


def init_s3_workspace_from_config(
    config: dict,
) -> Callable[
    [], tuple["ObjectStorageWriter", "ObjectStorageReader", "ObjectStorageDeleter"]
]:
    """从 's3' 段构建 s3 workspace initializer。

    's3' 段必须包含 'bucket' 字段。
    """
    from fyuneru import s3_toolkit

    s3_cfg = config["s3"]
    init = s3_toolkit.init_client(
        endpoint=s3_cfg["endpoint"],
        access_key_id=s3_cfg["access_key_id"],
        secret_access_key=s3_cfg["secret_access_key"],
        region_name=s3_cfg.get("region_name"),
    )
    bucket = s3_cfg["bucket"]
    return lambda: s3_toolkit.gen_s3worker(init(), bucket)


def init_mongo_database_from_config(config: dict) -> Callable[[], "Database"]:
    """从 'mongo' 段构建 MongoDB Database initializer。

    'mongo' 段必须包含 'db' 字段。
    """
    from fyuneru import mongo_toolkit

    mongo_cfg = config["mongo"]
    init = mongo_toolkit.init_client(
        uri=mongo_cfg["uri"],
        **({} if "timeout" not in mongo_cfg else {"timeout": mongo_cfg["timeout"]}),
    )
    db = mongo_cfg["db"]
    return lambda: init()[db]
