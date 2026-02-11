"""
配置构建器
"""

from pathlib import Path
from tomllib import load


def read_config(config: Path) -> dict:
    return load(config.open("rb"))


def default_choice(choice: list[str | int | None], default: str | int) -> str | int:
    for c in choice:
        if c is None:
            continue
        return c
    return default


def error_choice(choice: list[str | int | None]) -> str | int:
    for c in choice:
        if c is None:
            continue
        return c
    raise ValueError(f"No choice provided: {choice}")
