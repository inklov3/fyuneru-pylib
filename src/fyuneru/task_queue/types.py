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
    """actor 的内部绑定：handler 与 payload 类型。"""

    handler: TaskHandler
    payload_type: type[Any]


@dataclass(frozen=True)
class TaskMessage:
    """投递到队列的消息。"""

    queue_name: str
    payload: dict[str, Any]
