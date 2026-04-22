"""
配置构建器
"""

import os
from pathlib import Path
from typing import Any

from yaml import safe_load

from fyuneru.result import safe, unwrap


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


def read_config(config: Path) -> dict[str, list | dict]:
    return read_config_from_paths([config])


def read_config_with_override(
    base: Path,
    override: Path | None = None,
) -> dict[str, Any]:
    """读取 base 配置，并可选叠加一层 override 配置。"""
    if override is None:
        return read_config_from_paths([base])
    return read_config_from_paths([base, override])


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
