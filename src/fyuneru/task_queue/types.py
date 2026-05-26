from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fyuneru.result import ResultE


class TaskHandler(Protocol):
    __name__: str

    def __call__(self, payload: Any) -> Any: ...


class TaskActor(Protocol):
    queue_name: str

    def send(self, payload: Any) -> ResultE[str]: ...


@dataclass(frozen=True)
class ActorBinding:
    """actor 的内部绑定：handler、payload 类型、重试配置。

    ``max_retries=N`` 表示**最多 N 次额外重试**，一条消息最多被执行 N+1 次。
    重试延迟按 ``min(retry_backoff_ms_base * 2 ** attempt, retry_backoff_ms_max)``
    指数退避。
    """

    handler: TaskHandler
    payload_type: type[Any]
    max_retries: int = 0
    retry_backoff_ms_base: int = 1000
    retry_backoff_ms_max: int = 60_000


@dataclass(frozen=True)
class TaskMessage:
    """投递到队列的消息。

    ``attempt`` 表示**进入 handler 前已经被尝试过的次数**，首次投递为 0。
    """

    queue_name: str
    payload: dict[str, Any]
    attempt: int = 0
    eta: float | None = None
