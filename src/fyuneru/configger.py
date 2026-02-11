"""
配置构建器
"""

from pathlib import Path
from tomllib import load


def read_config(config: Path) -> dict[str, int | float | str]:
    return load(config.open("rb"))


def default_choice(
    choice: list[str | int | float | None], default: str | int | float
) -> str | int | float:
    for c in choice:
        if c is None:
            continue
        return c
    return default


def error_choice(choice: list[str | int | float | None]) -> str | int | float:
    for c in choice:
        if c is None:
            continue
        return c
    raise ValueError(f"No choice provided: {choice}")
