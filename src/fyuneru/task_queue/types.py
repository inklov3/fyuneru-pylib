from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fyuneru.result import ResultE


class TaskHandler(Protocol):
    __name__: str

    def __call__(self, payload: Any) -> Any: ...


class TaskActor(Protocol):
    name: str
    queue_name: str

    def send(self, payload: Any) -> ResultE[str]: ...


@dataclass(frozen=True)
class ActorBinding:
    handler: TaskHandler
    payload_type: type[Any]
    max_retries: int = 0


@dataclass(frozen=True)
class TaskMessage:
    name: str
    queue_name: str
    payload: dict[str, Any]
    attempt: int = 0
    eta: float | None = None
