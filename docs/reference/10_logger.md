# fyuneru.logger

基于 loguru 的日志初始化与 tqdm 集成。默认安装。

## API

```python
from fyuneru.logger import configure_logger, tqdm_loguru, LogLevel

# LogLevel: INFO, WARNING, ERROR, DEBUG

configure_logger(level: str = LogLevel.INFO, log_dir: Path | None = None) -> ResultE[None]
# @safe 装饰；调用方用 unwrap(result) 抛错。
# 配置 loguru：控制台输出 + 可选文件输出。
# 当 log_dir 设置时，创建带时间戳的日志文件 + latest.log。

tqdm_loguru(iterable, level="INFO", **tqdm_kwargs) -> tqdm
# tqdm 封装，进度通过 loguru 输出而不是 stderr。
```

## 关键约束（容易踩坑）

- **`configure_logger` 内部先 `logger.remove()` 清空所有已注册 handler**。重复调用会把日志通道完全重置，不要期望"再加一个 sink"语义。
- 如果你需要叠加自定义 sink，应该在 `configure_logger` 之后再 `from loguru import logger; logger.add(...)`。

## 用法

```python
from pathlib import Path

from fyuneru.logger import LogLevel, configure_logger, tqdm_loguru
from fyuneru.result import unwrap

unwrap(configure_logger(level=LogLevel.INFO, log_dir=Path("./logs")))

for item in tqdm_loguru(items, desc="Processing"):
    process(item)
```
