from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fyuneru.result import ResultE


class TaskHandler(Protocol):
    __name__: str

    def __call__(self, payload: dict[str, Any]) -> Any: ...


class TaskActor(Protocol):
    name: str
    queue_name: str

    def send(self, payload: Any) -> ResultE[str]: ...


@dataclass(frozen=True)
class TaskMessage:
    name: str
    queue_name: str
    payload: dict[str, Any]
    attempt: int = 0
    eta: float | None = None
