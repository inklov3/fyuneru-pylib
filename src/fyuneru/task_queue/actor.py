from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, is_dataclass
from traceback import format_exception
from typing import Any, cast, get_type_hints

from fyuneru.result import ResultE, safe
from fyuneru.task_queue.codec import normalize_payload_envelope
from fyuneru.task_queue.types import TaskHandler


@dataclass(frozen=True)
class RegisteredActor:
    _sender: Callable[[str, dict[str, Any]], str]
    queue_name: str
    handler: TaskHandler
    payload_type: type[Any]

    def __call__(self, payload: Any) -> Any:
        return self.handler(payload)

    @safe
    def send(self, payload: Any) -> str:
        payload_envelope = normalize_payload_envelope(payload, self.payload_type)
        return self._sender(self.queue_name, payload_envelope)


def actor(
    register: Callable[..., None],
    sender: Callable[[str, dict[str, Any]], str],
    queue_name: str = "default",
) -> Callable[[TaskHandler], RegisteredActor]:
    def decorator(function: TaskHandler) -> RegisteredActor:
        payload_type = resolve_payload_type(function)
        register(
            queue_name,
            function,
            payload_type,
        )
        return RegisteredActor(
            _sender=sender,
            queue_name=queue_name,
            handler=function,
            payload_type=payload_type,
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
    if not is_dataclass(payload_type):
        raise TypeError("payload 参数类型必须是 dataclass")
    return cast(type[Any], payload_type)


def build_xq_fields(
    original_id: str,
    queue_name: str,
    payload: str,
    error: Exception,
    failed_at: float,
) -> dict[str, str]:
    return {
        "original_id": original_id,
        "queue": queue_name,
        "payload": payload,
        "error": str(error),
        "traceback": _format_exception_safely(error),
        "failed_at": str(failed_at),
    }


def _format_exception_safely(error: Exception) -> str:
    """从异常对象本身格式化 traceback，避免依赖隐式 sys.exc_info。"""
    return "".join(format_exception(type(error), error, error.__traceback__))


def safe_send_message(
    sender: Callable[[str, dict[str, Any]], str],
    queue_name: str,
    payload: dict[str, Any],
) -> ResultE[str]:
    @safe
    def send() -> str:
        return sender(queue_name, payload)

    return send()
