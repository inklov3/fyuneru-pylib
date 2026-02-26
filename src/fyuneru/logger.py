"""
loguru日志模块
"""

from datetime import datetime
from pathlib import Path
from sys import stdout

from returns.result import safe
from tqdm import tqdm


class LogLevel:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"


@safe
def init_logger(level: str = LogLevel.INFO, log_dir: Path | None = None):
    from loguru import logger

    format = "{time:YYYY-MM-DD HH:mm:ss}<level>|{level}|{message}</level>"
    logger.remove()
    logger.add(sink=stdout, level=level, format=format)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{datetime.now():%Y-%m-%d_%H:%M:%S}.log"
        logger.add(
            str(log_path),
            format=format,
            level=level,
            enqueue=True,
            encoding="utf-8",
        )
        logger.add(
            str(log_dir / "latest.log"),
            format=format,
            level=level,
            enqueue=True,
            encoding="utf-8",
        )


def tqdm_loguru(iterable, level="INFO", **tqdm_kwargs):
    from loguru import logger

    """
    使用 loguru 打印 tqdm 进度的函数式包装器

    Args:
        iterable: 可迭代对象
        level: loguru 日志级别 (默认 INFO)
        **tqdm_kwargs: 传给 tqdm 的其它参数
    """

    class TqdmToLoguru:
        def __init__(self, log_level):
            self.log_level = log_level

        def write(self, buf):
            buf = buf.strip()
            if buf:
                logger.log(self.log_level, buf)

        def flush(self):
            pass

    return tqdm(iterable, file=TqdmToLoguru(level), **tqdm_kwargs)
