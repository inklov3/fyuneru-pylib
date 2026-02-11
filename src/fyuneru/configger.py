"""
配置构建器
"""

from pathlib import Path
from tomllib import load


def read_config(config: Path) -> dict[str, list | dict]:
    return load(config.open("rb"))
