"""有界重试：指数退避 + 抖动，只重试显式声明的异常类型。

`task_queue` 与 Ray 都只提供"整条任务重放"级别的重试，粒度过粗：
一次 429 不应该让已经下载并转码完成的单元从头再来。本模块补上
调用级别的有界重试，语义刻意收窄：

- 只重试 `retry_on` 列出的异常；其余异常立即透传（永久失败快速暴露）；
- 尝试次数有上限，耗尽后抛出最后一次异常本身，不包装成新类型；
- 退避带抖动，避免多 worker 同时撞同一个上游配额窗口。
"""

from collections.abc import Callable
from dataclasses import dataclass
from random import uniform
from time import sleep
from typing import TypeVar

from loguru import logger

from fyuneru.result import ResultE, safe

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """有界退避参数。

    `attempts` 是总尝试次数（含首次），所以 1 表示不重试。
    """

    attempts: int = 3
    base_seconds: float = 1.0
    max_seconds: float = 30.0
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts 必须大于 0")
        if self.base_seconds <= 0:
            raise ValueError("base_seconds 必须大于 0")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds 不能小于 base_seconds")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter 必须在 [0, 1] 区间")

    def delay_for(self, attempt: int) -> float:
        """返回第 `attempt` 次失败后的等待秒数（attempt 从 1 开始）。"""
        if attempt < 1:
            raise ValueError("attempt 必须大于 0")
        raw = self.base_seconds * (2 ** (attempt - 1))
        capped = min(raw, self.max_seconds)
        if self.jitter == 0:
            return capped
        return capped * uniform(1 - self.jitter, 1 + self.jitter)


def retry_call(
    operation: Callable[[], T],
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "operation",
    sleeper: Callable[[float], None] = sleep,
) -> T:
    """执行 `operation`，对 `retry_on` 内的异常做有界退避重试。

    耗尽预算后抛出最后一次捕获的异常，调用方据此分类永久失败。
    `sleeper` 可注入以便测试不真的睡眠。
    """
    active = policy if policy is not None else RetryPolicy()
    last_error: BaseException | None = None
    for attempt in range(1, active.attempts + 1):
        try:
            return operation()
        except retry_on as error:
            last_error = error
            if attempt >= active.attempts:
                break
            delay = active.delay_for(attempt)
            logger.warning(
                "retry.backoff label={} attempt={}/{} delay={:.2f}s error={}",
                label,
                attempt,
                active.attempts,
                delay,
                error,
            )
            sleeper(delay)
    if last_error is None:
        raise RuntimeError("retry_call 未产生结果也未捕获异常")
    raise last_error


def bind_retrying(
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "operation",
) -> Callable[[Callable[[], T]], ResultE[T]]:
    """返回把 `retry_call` 结果包成 `ResultE` 的执行器。"""

    @safe
    def execute(operation: Callable[[], T]) -> T:
        return retry_call(
            operation,
            policy=policy,
            retry_on=retry_on,
            label=label,
        )

    return execute
