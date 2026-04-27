from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, is_dataclass
from traceback import format_exc
from typing import Any, get_type_hints

from fyuneru.result import ResultE, safe
from fyuneru.task_queue.codec import normalize_payload_envelope
from fyuneru.task_queue.types import TaskHandler


@dataclass(frozen=True)
class RegisteredActor:
    _sender: Callable[[str, str, dict[str, Any], int, float | None], str]
    name: str
    queue_name: str
    handler: TaskHandler
    payload_type: type[Any]
    max_retries: int = 0

    def __call__(self, payload: Any) -> Any:
        return self.handler(payload)

    @safe
    def send(self, payload: Any) -> str:
        payload_envelope = normalize_payload_envelope(payload, self.payload_type)
        return self._sender(self.queue_name, self.name, payload_envelope, 0, None)


def actor(
    register: Callable[[str, str, TaskHandler, type[Any], int], None],
    sender: Callable[[str, str, dict[str, Any], int, float | None], str],
    queue_name: str = "default",
    name: str | None = None,
    max_retries: int = 0,
) -> Callable[[TaskHandler], RegisteredActor]:
    if max_retries < 0:
        raise ValueError("max_retries 不能小于 0")

    def decorator(function: TaskHandler) -> RegisteredActor:
        actor_name = function.__name__ if name is None else name
        payload_type = resolve_payload_type(function)
        register(queue_name, actor_name, function, payload_type, max_retries)
        return RegisteredActor(
            _sender=sender,
            name=actor_name,
            queue_name=queue_name,
            handler=function,
            payload_type=payload_type,
            max_retries=max_retries,
        )

    return decorator


def resolve_payload_type(function: TaskHandler) -> type[Any]:
    signature = inspect.signature(function)
    positional_parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if len(positional_parameters) != 1:
        raise TypeError("actor 函数必须且仅能声明一个 payload 参数")

    parameter = positional_parameters[0]
    if parameter.annotation is inspect.Parameter.empty:
        raise TypeError("payload 参数必须声明 dataclass 类型注解")

    type_hints = get_type_hints(function)
    payload_type = type_hints.get(parameter.name)
    if payload_type is None:
        raise TypeError("payload 参数必须声明 dataclass 类型注解")
    if not isinstance(payload_type, type):
        raise TypeError("payload 参数类型必须是 dataclass")
    if not is_dataclass(payload_type):
        raise TypeError("payload 参数类型必须是 dataclass")
    return payload_type


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
