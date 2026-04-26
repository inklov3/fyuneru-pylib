from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from traceback import format_exc
from typing import Any

from fyuneru.result import ResultE, safe
from fyuneru.task_queue.codec import normalize_payload
from fyuneru.task_queue.types import TaskHandler


@dataclass(frozen=True)
class RegisteredActor:
    _sender: Callable[[str, str, dict[str, Any], int, float | None], str]
    name: str
    queue_name: str
    handler: TaskHandler

    def __call__(self, payload: dict[str, Any]) -> Any:
        return self.handler(payload)

    @safe
    def send(self, payload: Any) -> str:
        normalized_payload = normalize_payload(payload)
        return self._sender(self.queue_name, self.name, normalized_payload, 0, None)


def actor(
    register: Callable[[str, str, TaskHandler], None],
    sender: Callable[[str, str, dict[str, Any], int, float | None], str],
    queue_name: str = "default",
    name: str | None = None,
) -> Callable[[TaskHandler], RegisteredActor]:
    def decorator(function: TaskHandler) -> RegisteredActor:
        actor_name = function.__name__ if name is None else name
        register(queue_name, actor_name, function)
        return RegisteredActor(
            _sender=sender,
            name=actor_name,
            queue_name=queue_name,
            handler=function,
        )

    return decorator


def build_xq_fields(
    original_id: str,
    queue_name: str,
    actor_name: str,
    payload: str,
    attempt: int,
    error: Exception,
    failed_at: float,
) -> dict[str, str]:
    return {
        "original_id": original_id,
        "queue": queue_name,
        "name": actor_name,
        "payload": payload,
        "attempt": str(attempt),
        "error": str(error),
        "traceback": format_exc(),
        "failed_at": str(failed_at),
    }


def safe_send_message(
    sender: Callable[[str, str, dict[str, Any], int, float | None], str],
    queue_name: str,
    name: str,
    payload: dict[str, Any],
    attempt: int,
    eta: float | None,
) -> ResultE[str]:
    @safe
    def send() -> str:
        return sender(queue_name, name, payload, attempt, eta)

    return send()
