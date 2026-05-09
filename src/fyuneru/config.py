"""
配置构建器
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yaml import safe_load

from fyuneru.result import safe, unwrap


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    db: int
    password: str | None
    cluster: bool


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    access_key_id: str
    secret_access_key: str
    region_name: str | None
    bucket: str | None
    addressing_style: str


@dataclass(frozen=True)
class MongoConfig:
    uri: str
    db: str | None
    timeout: int


@safe
def _read_yaml_mapping(config: Path) -> dict[str, Any]:
    loaded = safe_load(config.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("配置文件根节点必须是对象映射")
    return loaded


def read_config_from_paths(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("配置路径列表不能为空")
    merged: dict[str, Any] = {}
    for p in paths:
        if not p:
            raise ValueError("配置路径不能为空")
        if not p.exists():
            raise FileNotFoundError(f"配置文件不存在: {p}")
        loaded = unwrap(_read_yaml_mapping(p))
        merged = _merge_config_value(merged, loaded, ())
    return merged


def read_config_from_env() -> dict[str, Any]:
    env_var = "FYUNERU_CONFIG_PATHS"
    value = os.environ.get(env_var)
    if not value:
        raise ValueError(f"环境变量 {env_var} 未设置")
    path_strs = value.split(":")
    if not path_strs or path_strs == [""]:
        raise ValueError(f"环境变量 {env_var} 不能为空")
    paths = [Path(p) for p in path_strs]
    return read_config_from_paths(paths)


def read_config(config: Path) -> dict[str, Any]:
    return read_config_from_paths([config])


def read_config_with_override(
    base: Path,
    override: Path | None = None,
) -> dict[str, Any]:
    """读取 base 配置，并可选叠加一层 override 配置。"""
    if override is None:
        return read_config_from_paths([base])
    return read_config_from_paths([base, override])


def parse_redis_config(config: dict[str, Any]) -> RedisConfig:
    redis_cfg = _require_mapping(config, "redis")
    host = _require_text(redis_cfg, "host", "redis.host")
    port = _require_int(redis_cfg, "port", "redis.port")
    db = _optional_int(redis_cfg, "db", "redis.db", 0)
    password = _optional_text(redis_cfg, "password", "redis.password")
    cluster = _optional_bool(redis_cfg, "cluster", "redis.cluster", False)
    return RedisConfig(
        host=host,
        port=port,
        db=db,
        password=password,
        cluster=cluster,
    )


def parse_s3_config(config: dict[str, Any]) -> S3Config:
    s3_cfg = _require_mapping(config, "s3")
    endpoint = _require_text(s3_cfg, "endpoint", "s3.endpoint")
    access_key_id = _require_text(s3_cfg, "access_key_id", "s3.access_key_id")
    secret_access_key = _require_text(
        s3_cfg,
        "secret_access_key",
        "s3.secret_access_key",
    )
    region_name = _optional_text(s3_cfg, "region_name", "s3.region_name")
    bucket = _optional_text(s3_cfg, "bucket", "s3.bucket")
    addressing_style = _optional_text(
        s3_cfg,
        "addressing_style",
        "s3.addressing_style",
        "virtual",
    )
    if addressing_style not in {"virtual", "path"}:
        raise ValueError(
            "s3.addressing_style 仅支持 'virtual' 或 'path'"
        )

    return S3Config(
        endpoint=endpoint,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region_name=region_name,
        bucket=bucket,
        addressing_style=addressing_style,
    )


def parse_mongo_config(config: dict[str, Any]) -> MongoConfig:
    mongo_cfg = _require_mapping(config, "mongo")
    uri = _require_text(mongo_cfg, "uri", "mongo.uri")
    db = _optional_text(mongo_cfg, "db", "mongo.db")
    timeout = _optional_int(mongo_cfg, "timeout", "mongo.timeout", 1000 * 10)
    return MongoConfig(uri=uri, db=db, timeout=timeout)


def _merge_config_value(base: Any, override: Any, path: tuple[str, ...]) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, override_value in override.items():
            key_name = str(key)
            next_path = (*path, key_name)
            if key in merged:
                merged[key] = _merge_config_value(
                    merged[key], override_value, next_path
                )
            else:
                merged[key] = _merge_config_value(None, override_value, next_path)
        return merged

    if isinstance(base, list) and isinstance(override, list):
        return [*base, *override]

    return override


def _require_mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in config:
        raise KeyError(f"缺少字段: {key}")
    value = config[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} 必须是对象映射")
    return value


def _require_text(config: dict[str, Any], key: str, path: str) -> str:
    if key not in config:
        raise KeyError(f"缺少字段: {path}")
    value = config[key]
    if not isinstance(value, str):
        raise TypeError(f"{path} 必须是字符串")
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{path} 不能为空")
    return normalized


def _optional_text(
    config: dict[str, Any],
    key: str,
    path: str,
    default: str | None = None,
) -> str | None:
    if key not in config:
        return default
    value = config[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{path} 必须是字符串")
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{path} 不能为空")
    return normalized


def _require_int(config: dict[str, Any], key: str, path: str) -> int:
    if key not in config:
        raise KeyError(f"缺少字段: {path}")
    value = config[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{path} 必须是整数")
    return value


def _optional_int(
    config: dict[str, Any],
    key: str,
    path: str,
    default: int,
) -> int:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{path} 必须是整数")
    return value


def _optional_bool(
    config: dict[str, Any],
    key: str,
    path: str,
    default: bool,
) -> bool:
    if key not in config:
        return default
    value = config[key]
    if not isinstance(value, bool):
        raise TypeError(f"{path} 必须是布尔值")
    return value
