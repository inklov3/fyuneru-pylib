from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from typing import Any, cast
from uuid import uuid4

from redis import Redis, RedisCluster
from redis.exceptions import ResponseError

from fyuneru.result import ResultE
from fyuneru.task_queue.actor import (
    RegisteredActor,
    safe_send_message,
)
from fyuneru.task_queue.actor import (
    actor as register_actor,
)
from fyuneru.task_queue.codec import encode_payload, normalize_payload
from fyuneru.task_queue.lua_scripts import load_lua_scripts
from fyuneru.task_queue.types import TaskHandler, TaskMessage
from fyuneru.task_queue.worker import run_worker


@dataclass
class TaskQueueBroker:
    redis_client: Redis | RedisCluster
    namespace: str
    group_name: str
    max_retries: int = 0
    claim_idle_ms: int | None = None
    xq_stream: str | None = None
    _actors: dict[str, dict[str, TaskHandler]] = field(default_factory=dict)
    _group_ready_streams: set[str] = field(default_factory=set)
    _scripts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not hasattr(self.redis_client, "register_script"):
            self._scripts = {}
            return

        try:
            register_script = cast(Any, self.redis_client).register_script
            self._scripts = {
                name: register_script(script)
                for name, script in load_lua_scripts().items()
            }
        except Exception:
            self._scripts = {}

    def actor(
        self,
        queue_name: str = "default",
        name: str | None = None,
    ) -> Callable[[TaskHandler], RegisteredActor]:
        return register_actor(
            register=self._register_actor,
            sender=self._send_payload,
            queue_name=queue_name,
            name=name,
        )

    def enqueue(self, message: TaskMessage) -> str:
        return self._send_payload(
            queue_name=message.queue_name,
            name=message.name,
            payload=message.payload,
            attempt=message.attempt,
            eta=message.eta,
        )

    def run_worker(
        self,
        queue_name: str = "default",
        consumer_name: str = "worker-1",
        block_ms: int = 1000,
        max_messages: int | None = None,
        stop_when_idle: bool = False,
    ) -> ResultE[int]:
        return run_worker(
            broker=self,
            queue_name=queue_name,
            consumer_name=consumer_name,
            block_ms=block_ms,
            max_messages=max_messages,
            stop_when_idle=stop_when_idle,
        )

    def _register_actor(
        self, queue_name: str, actor_name: str, handler: TaskHandler
    ) -> None:
        self._actors.setdefault(queue_name, {})[actor_name] = handler

    def _send_payload(
        self,
        queue_name: str,
        name: str,
        payload: dict[str, Any],
        attempt: int,
        eta: float | None = None,
    ) -> str:
        stream = self._stream_name(queue_name)
        fields: dict[Any, Any] = {
            "id": self._next_retry_message_id(),
            "name": name,
            "payload": encode_payload(payload),
            "attempt": str(attempt),
            "eta": "" if eta is None else str(eta),
            "created_at": str(time()),
        }
        message_id = self.redis_client.xadd(stream, fields)
        return _to_text(message_id)

    def _retry_and_ack(
        self,
        source_stream: str,
        queue_stream: str,
        group_name: str,
        message_id: str,
        retry_id: str,
        name: str,
        payload: str,
        attempt: int,
        created_at: float,
    ) -> str:
        script = self._scripts.get("retry_and_ack")
        eta = ""
        if script is not None:
            retry_stream_id = script(
                keys=[source_stream, queue_stream],
                args=[
                    group_name,
                    message_id,
                    retry_id,
                    name,
                    payload,
                    str(attempt),
                    eta,
                    str(created_at),
                ],
            )
            return _to_text(retry_stream_id)

        retry_stream_id = self.redis_client.xadd(
            queue_stream,
            {
                "id": retry_id,
                "name": name,
                "payload": payload,
                "attempt": str(attempt),
                "eta": eta,
                "created_at": str(created_at),
            },
        )
        self.redis_client.xack(source_stream, group_name, message_id)
        return _to_text(retry_stream_id)

    def _xq_and_ack(
        self,
        source_stream: str,
        xq_stream: str,
        group_name: str,
        message_id: str,
        xq_fields: dict[str, str],
    ) -> str:
        script = self._scripts.get("xq_and_ack")
        if script is not None:
            xq_stream_id = script(
                keys=[source_stream, xq_stream],
                args=[
                    group_name,
                    message_id,
                    xq_fields["original_id"],
                    xq_fields["queue"],
                    xq_fields["name"],
                    xq_fields["payload"],
                    xq_fields["attempt"],
                    xq_fields["error"],
                    xq_fields["traceback"],
                    xq_fields["failed_at"],
                ],
            )
            return _to_text(xq_stream_id)

        xq_stream_id = self.redis_client.xadd(
            xq_stream, cast(dict[Any, Any], xq_fields)
        )
        self.redis_client.xack(source_stream, group_name, message_id)
        return _to_text(xq_stream_id)

    def _stream_name(self, queue_name: str) -> str:
        return f"{self.namespace}:{queue_name}"

    def _xq_stream_name(self) -> str:
        if self.xq_stream is not None:
            return self.xq_stream
        return f"{self.namespace}:xq"

    def _next_retry_message_id(self) -> str:
        return str(uuid4())

    def _ensure_group(self, stream: str) -> None:
        if stream in self._group_ready_streams:
            return

        try:
            self.redis_client.xgroup_create(
                name=stream,
                groupname=self.group_name,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

        self._group_ready_streams.add(stream)

    def _claim_entries(
        self,
        stream: str,
        consumer_name: str,
    ) -> list[tuple[str, dict[Any, Any]]]:
        if self.claim_idle_ms is None:
            return []

        result = self.redis_client.xautoclaim(
            name=stream,
            groupname=self.group_name,
            consumername=consumer_name,
            min_idle_time=self.claim_idle_ms,
            start_id="0-0",
            count=10,
        )
        if not isinstance(result, (list, tuple)):
            return []
        if len(result) < 2:
            return []

        raw_entries = result[1]
        if not isinstance(raw_entries, list):
            return []

        entries: list[tuple[str, dict[Any, Any]]] = []
        for message_id, fields in raw_entries:
            entries.append((_to_text(message_id), fields))
        return entries

    def _flatten_entries(self, response: Any) -> list[tuple[str, dict[Any, Any]]]:
        entries: list[tuple[str, dict[Any, Any]]] = []
        if not isinstance(response, list):
            return entries

        for stream_entries in response:
            if not isinstance(stream_entries, tuple) or len(stream_entries) != 2:
                continue
            _, items = stream_entries
            if not isinstance(items, list):
                continue
            for message_id, fields in items:
                entries.append((_to_text(message_id), fields))
        return entries

    def _normalize_stream_fields(self, fields: dict[Any, Any]) -> dict[str, str]:
        return {_to_text(key): _to_text(value) for key, value in fields.items()}


def calculate_namespace(worker: str, task: str) -> str:
    return f"{worker}:{{{task}}}"


def build_broker(
    redis_client: Redis | RedisCluster,
    namespace: str,
    group_name: str = "default",
    max_retries: int = 0,
    claim_idle_ms: int | None = None,
    xq_stream: str | None = None,
) -> TaskQueueBroker:
    if max_retries < 0:
        raise ValueError("max_retries 不能小于 0")
    if claim_idle_ms is not None and claim_idle_ms <= 0:
        raise ValueError("claim_idle_ms 必须大于 0")

    return TaskQueueBroker(
        redis_client=redis_client,
        namespace=namespace,
        group_name=group_name,
        max_retries=max_retries,
        claim_idle_ms=claim_idle_ms,
        xq_stream=xq_stream,
    )


def new_message(
    name: str,
    queue_name: str,
    payload: Any,
    attempt: int = 0,
    eta: float | None = None,
) -> TaskMessage:
    if attempt < 0:
        raise ValueError("attempt 不能小于 0")

    normalized_payload = normalize_payload(payload)
    return TaskMessage(
        name=name,
        queue_name=queue_name,
        payload=normalized_payload,
        attempt=attempt,
        eta=eta,
    )


def send_message(
    broker: TaskQueueBroker,
    message: TaskMessage,
) -> ResultE[str]:
    return safe_send_message(
        sender=broker._send_payload,
        queue_name=message.queue_name,
        name=message.name,
        payload=message.payload,
        attempt=message.attempt,
        eta=message.eta,
    )


def actor(
    broker: TaskQueueBroker,
    queue_name: str = "default",
    name: str | None = None,
) -> Callable[[TaskHandler], RegisteredActor]:
    return broker.actor(queue_name=queue_name, name=name)


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
