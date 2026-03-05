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


def init_redis_from_config(config: dict) -> Callable:
    """从 config dict 的 'redis' 段构建 redis client initializer。缺少 'redis' 段则抛 KeyError。"""
    from fyuneru import redis_toolkit

    redis_cfg = config["redis"]
    if redis_cfg.get("cluster", False):
        return redis_toolkit.init_client_cluster(
            host=redis_cfg["host"], port=redis_cfg["port"]
        )
    return redis_toolkit.init_client_standalone(
        host=redis_cfg["host"], port=redis_cfg["port"], db=redis_cfg.get("db", 0)
    )


def init_s3_from_config(config: dict) -> Callable:
    """从 config dict 的 's3' 段构建 s3 client initializer。缺少 's3' 段则抛 KeyError。"""
    from fyuneru import s3_toolkit

    s3_cfg = config["s3"]
    return s3_toolkit.init_client(
        endpoint=s3_cfg["endpoint"],
        access_key_id=s3_cfg["access_key_id"],
        secret_access_key=s3_cfg["secret_access_key"],
        region_name=s3_cfg.get("region_name"),
    )


def init_mongo_from_config(config: dict) -> Callable:
    """从 config dict 的 'mongo' 段构建 mongo client initializer。缺少 'mongo' 段则抛 KeyError。"""
    from fyuneru import mongo_toolkit

    mongo_cfg = config["mongo"]
    kwargs = {"uri": mongo_cfg["uri"]}
    if "timeout" in mongo_cfg:
        kwargs["timeout"] = mongo_cfg["timeout"]
    return mongo_toolkit.init_client(**kwargs)


def init_llm_from_config(config: dict) -> Callable:
    """从 config dict 的 'llm' 段构建 LLM client initializer。缺少 'llm' 段则抛 KeyError。"""
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
