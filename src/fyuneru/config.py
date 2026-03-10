"""
配置构建器
"""

from collections.abc import Callable
from pathlib import Path

from yaml import safe_load


def read_config(config: Path) -> dict[str, list | dict]:
    suffix = config.suffix
    if suffix in (".yaml", ".yml"):
        return safe_load(config.read_text(encoding="utf-8"))
    raise ValueError(f"不支持的配置文件格式: {suffix}")


# ---------------------------------------------------------------------------
# 底层 client initializer — 返回裸客户端工厂，与各 toolkit 的 init_* 对齐
# ---------------------------------------------------------------------------


def init_redis_from_config(config: dict) -> Callable:
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


def init_s3_from_config(config: dict) -> Callable:
    """从 's3' 段构建 s3 client initializer。

    返回 Callable[[], S3Client]。
    """
    from fyuneru import s3_toolkit

    s3_cfg = config["s3"]
    return s3_toolkit.init_client(
        endpoint=s3_cfg["endpoint"],
        access_key_id=s3_cfg["access_key_id"],
        secret_access_key=s3_cfg["secret_access_key"],
        region_name=s3_cfg.get("region_name"),
    )


def init_mongo_from_config(config: dict) -> Callable:
    """从 'mongo' 段构建 mongo client initializer。

    返回 Callable[[], MongoClient]。
    """
    from fyuneru import mongo_toolkit

    mongo_cfg = config["mongo"]
    kwargs: dict = {"uri": mongo_cfg["uri"]}
    if "timeout" in mongo_cfg:
        kwargs["timeout"] = mongo_cfg["timeout"]
    return mongo_toolkit.init_client(**kwargs)


def init_llm_from_config(config: dict) -> Callable:
    """从 'llm' 段构建 LLM client initializer。

    返回 Callable[[], Client]。
    """
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


def init_s3_workspace_from_config(config: dict) -> Callable:
    """从 's3' 段构建 s3 workspace initializer。

    's3' 段必须包含 'bucket' 字段。
    返回 Callable[[], tuple[ObjectStorageWriter, ObjectStorageReader, ObjectStorageDeleter]]。
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


def init_mongo_database_from_config(config: dict) -> Callable:
    """从 'mongo' 段构建 MongoDB Database initializer。

    'mongo' 段必须包含 'db' 字段。
    返回 Callable[[], Database]。
    """
    from fyuneru import mongo_toolkit

    mongo_cfg = config["mongo"]
    init = mongo_toolkit.init_client(
        uri=mongo_cfg["uri"],
        **({} if "timeout" not in mongo_cfg else {"timeout": mongo_cfg["timeout"]}),
    )
    db = mongo_cfg["db"]
    return lambda: init()[db]
