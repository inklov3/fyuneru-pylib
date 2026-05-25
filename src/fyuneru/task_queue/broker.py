from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from typing import Any, cast
from uuid import uuid4

from loguru import logger
from redis import Redis, RedisCluster
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from fyuneru.result import ResultE
from fyuneru.task_queue.actor import (
    RegisteredActor,
    build_xq_fields,
    safe_send_message,
)
from fyuneru.task_queue.actor import (
    actor as register_actor,
)
from fyuneru.task_queue.codec import (
    decode_payload,
    encode_payload,
    normalize_payload_envelope,
)
from fyuneru.task_queue.lua_scripts import load_lua_scripts
from fyuneru.task_queue.protocols import (
    BadEntry,
    BrokerHooks,
    Entry,
    ReadOutcome,
)
from fyuneru.task_queue.types import ActorBinding, TaskHandler, TaskMessage
from fyuneru.task_queue.worker import run_worker


@dataclass
class TaskQueueBroker:
    """Redis Streams 任务 broker，实现 :class:`BrokerOps` Protocol。"""

    redis_client: Redis | RedisCluster
    namespace: str
    group_name: str
    claim_idle_ms: int | None = None
    xq_stream: str | None = None
    xq_maxlen: int | None = None
    hooks: BrokerHooks = field(default_factory=BrokerHooks)
    _actors: dict[str, dict[str, ActorBinding]] = field(default_factory=dict)
    _group_ready_streams: set[str] = field(default_factory=set)
    _scripts: dict[str, Any] = field(default_factory=dict)
    _lua_degraded: bool = False

    def __post_init__(self) -> None:
        if self.xq_maxlen is not None and self.xq_maxlen <= 0:
            raise ValueError("xq_maxlen 必须大于 0")

        if not hasattr(self.redis_client, "register_script"):
            self._scripts = {}
            self._mark_lua_degraded("redis client 不支持 register_script")
            return

        try:
            register_script = cast(Any, self.redis_client).register_script
            self._scripts = {
                name: register_script(script)
                for name, script in load_lua_scripts().items()
            }
        except Exception as error:
            self._scripts = {}
            self._mark_lua_degraded(
                f"Lua 脚本注册失败，降级为非原子 xadd+xack ({error})"
            )

    # ------------------------------------------------------------------
    # 公开装饰器 / 入队 API
    # ------------------------------------------------------------------

    def actor(
        self,
        queue_name: str = "default",
        name: str | None = None,
        max_retries: int = 0,
        retry_backoff_ms_base: int = 1000,
        retry_backoff_ms_max: int = 60_000,
    ) -> Callable[[TaskHandler], RegisteredActor]:
        return register_actor(
            register=self._register_actor,
            sender=self._send_payload,
            queue_name=queue_name,
            name=name,
            max_retries=max_retries,
            retry_backoff_ms_base=retry_backoff_ms_base,
            retry_backoff_ms_max=retry_backoff_ms_max,
        )

    def enqueue(self, message: TaskMessage) -> str:
        return self._send_payload(
            queue_name=message.queue_name,
            name=message.name,
            payload=message.payload,
            attempt=message.attempt,
            eta=message.eta,
        )

    def enqueue_many(self, messages: list[TaskMessage]) -> list[ResultE[str]]:
        if not messages:
            return []
        if not _client_supports_pipeline(self.redis_client):
            return [
                safe_send_message(
                    sender=self._send_payload,
                    queue_name=message.queue_name,
                    name=message.name,
                    payload=message.payload,
                    attempt=message.attempt,
                    eta=message.eta,
                )
                for message in messages
            ]
        return self._enqueue_many_pipelined(messages)

    def run_worker(
        self,
        queue_name: str = "default",
        consumer_name: str = "worker-1",
        block_ms: int = 1000,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        return run_worker(
            broker=self,
            queue_name=queue_name,
            consumer_name=consumer_name,
            block_ms=block_ms,
            should_stop=should_stop,
        )

    # ------------------------------------------------------------------
    # BrokerOps 接口（worker 通过 Protocol 调用，全部为公开方法）
    # ------------------------------------------------------------------

    def stream_for(self, queue_name: str) -> str:
        return f"{self.namespace}:{queue_name}"

    def xq_stream_for(self) -> str:
        if self.xq_stream is not None:
            return self.xq_stream
        return f"{self.namespace}:xq"

    def ensure_group(self, stream: str) -> None:
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

    def actor_for(self, queue_name: str, actor_name: str) -> ActorBinding | None:
        return self._actors.get(queue_name, {}).get(actor_name)

    def read_entries(
        self,
        stream: str,
        queue_name: str,
        consumer_name: str,
        block_ms: int,
    ) -> ReadOutcome:
        """读取一批消息并完成解析。

        Redis 连接 / 超时类异常被捕获后通过 ``ReadOutcome.redis_error`` 返回；
        其余字段级错误统一归入 ``bad_entries``。worker 拿到的就是已分类好的结果。
        """
        try:
            raw = self._read_raw(stream, consumer_name, block_ms)
        except (RedisConnectionError, RedisTimeoutError) as error:
            self.notify_hook("on_redis_error", error)
            return ReadOutcome(redis_error=error)

        entries: list[Entry] = []
        bad_entries: list[BadEntry] = []
        for message_id, raw_fields in raw:
            classification = self._classify(stream, queue_name, message_id, raw_fields)
            if isinstance(classification, Entry):
                entries.append(classification)
            else:
                bad_entries.append(classification)
        return ReadOutcome(entries=entries, bad_entries=bad_entries)

    def handle_success(self, entry: Entry) -> None:
        self.redis_client.xack(entry.stream, self.group_name, entry.message_id)

    def handle_retry(self, entry: Entry, error: Exception) -> None:
        next_attempt = entry.attempt + 1
        eta = self._calculate_eta(entry.binding, entry.attempt)
        self._retry_and_ack(
            source_stream=entry.stream,
            queue_stream=self.stream_for(entry.queue_name),
            message_id=entry.message_id,
            retry_id=self._next_retry_message_id(),
            name=entry.actor_name,
            payload=entry.payload_raw,
            attempt=next_attempt,
            eta=eta,
            created_at=time(),
        )
        self.notify_hook(
            "on_handle_retry",
            entry.queue_name,
            entry.actor_name,
            next_attempt,
            error,
        )

    def handle_defer(self, entry: Entry) -> None:
        if entry.eta is None:
            raise ValueError("handle_defer 仅适用于 eta 非空的消息")
        self._defer_and_ack(
            source_stream=entry.stream,
            queue_stream=self.stream_for(entry.queue_name),
            message_id=entry.message_id,
            defer_id=self._next_retry_message_id(),
            name=entry.actor_name,
            payload=entry.payload_raw,
            attempt=entry.attempt,
            eta=entry.eta,
            created_at=entry.created_at,
        )

    def handle_xq_for_entry(self, entry: Entry, error: Exception) -> None:
        xq_fields = build_xq_fields(
            original_id=entry.message_id,
            queue_name=entry.queue_name,
            actor_name=entry.actor_name,
            payload=entry.payload_raw,
            attempt=entry.attempt,
            error=error,
            failed_at=time(),
        )
        self._xq_and_ack(
            source_stream=entry.stream,
            group_name=self.group_name,
            message_id=entry.message_id,
            xq_fields=xq_fields,
        )
        self.notify_hook(
            "on_handle_xq",
            entry.queue_name,
            entry.actor_name,
            entry.attempt,
            error,
        )

    def handle_xq_for_bad(self, bad: BadEntry) -> None:
        xq_fields = build_xq_fields(
            original_id=bad.message_id,
            queue_name=bad.queue_name,
            actor_name=bad.actor_name or "<unknown>",
            payload=bad.payload_raw if bad.payload_raw is not None else "",
            attempt=bad.attempt,
            error=bad.error,
            failed_at=time(),
        )
        # 把 BadEntry 的失败原因附在 error 字段前缀，便于排障
        xq_fields["error"] = f"[{bad.reason}] {xq_fields['error']}"
        self._xq_and_ack(
            source_stream=bad.stream,
            group_name=self.group_name,
            message_id=bad.message_id,
            xq_fields=xq_fields,
        )
        self.notify_hook(
            "on_handle_xq",
            bad.queue_name,
            bad.actor_name or "<unknown>",
            bad.attempt,
            bad.error,
        )

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _register_actor(
        self,
        queue_name: str,
        actor_name: str,
        handler: TaskHandler,
        payload_type: type[Any],
        max_retries: int,
        retry_backoff_ms_base: int,
        retry_backoff_ms_max: int,
    ) -> None:
        self._actors.setdefault(queue_name, {})[actor_name] = ActorBinding(
            handler=handler,
            payload_type=payload_type,
            max_retries=max_retries,
            retry_backoff_ms_base=retry_backoff_ms_base,
            retry_backoff_ms_max=retry_backoff_ms_max,
        )

    def _send_payload(
        self,
        queue_name: str,
        name: str,
        payload: dict[str, Any],
        attempt: int,
        eta: float | None = None,
    ) -> str:
        stream = self.stream_for(queue_name)
        fields = {
            "id": self._next_retry_message_id(),
            "name": name,
            "payload": encode_payload(payload),
            "attempt": str(attempt),
            "eta": "" if eta is None else str(eta),
            "created_at": str(time()),
        }
        message_id = self.redis_client.xadd(stream, cast(dict[Any, Any], fields))
        self.notify_hook("on_enqueue", queue_name, name, attempt)
        return _to_text(message_id)

    def _enqueue_many_pipelined(
        self, messages: list[TaskMessage]
    ) -> list[ResultE[str]]:
        from fyuneru.result import Failure, Success

        results: list[ResultE[str]] = [cast(ResultE[str], None)] * len(messages)
        buckets: dict[str, list[int]] = {}
        prepared: list[tuple[str, dict[str, str]]] = []
        for index, message in enumerate(messages):
            try:
                stream = self.stream_for(message.queue_name)
                fields = {
                    "id": self._next_retry_message_id(),
                    "name": message.name,
                    "payload": encode_payload(message.payload),
                    "attempt": str(message.attempt),
                    "eta": "" if message.eta is None else str(message.eta),
                    "created_at": str(time()),
                }
                prepared.append((stream, fields))
                buckets.setdefault(stream, []).append(index)
            except Exception as error:
                results[index] = Failure(error)
                prepared.append(("", {}))

        for stream, indices in buckets.items():
            try:
                pipeline = cast(Any, self.redis_client).pipeline(transaction=False)
                for index in indices:
                    _, fields = prepared[index]
                    pipeline.xadd(stream, cast(dict[Any, Any], fields))
                # raise_on_error=False：让单条命令的异常以 Exception 对象形式留在结果列表，
                # 我们逐条判断；否则首个失败的命令会让整个 bucket 一起报 Failure，但
                # 服务端可能已成功执行了前面几条 XADD。
                raw_ids = pipeline.execute(raise_on_error=False)
            except Exception as error:
                for index in indices:
                    if results[index] is None:
                        results[index] = Failure(error)
                continue

            for offset, index in enumerate(indices):
                if results[index] is not None:
                    # 已经在 prep 阶段被标记为 Failure，不被 pipeline 的成功响应覆盖。
                    continue
                if offset >= len(raw_ids):
                    results[index] = Failure(
                        RuntimeError("pipeline 返回结果数量与预期不符")
                    )
                    continue
                raw_id = raw_ids[offset]
                if isinstance(raw_id, Exception):
                    results[index] = Failure(raw_id)
                    continue
                results[index] = Success(_to_text(raw_id))
                message = messages[index]
                self.notify_hook(
                    "on_enqueue", message.queue_name, message.name, message.attempt
                )

        return results

    def _read_raw(
        self,
        stream: str,
        consumer_name: str,
        block_ms: int,
    ) -> list[tuple[str, dict[Any, Any]]]:
        claimed = self._claim_entries(stream, consumer_name)
        if claimed:
            return claimed

        response = self.redis_client.xreadgroup(
            groupname=self.group_name,
            consumername=consumer_name,
            streams={stream: ">"},
            count=1,
            block=block_ms,
        )
        return _flatten_entries(response)

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

    def _classify(
        self,
        stream: str,
        queue_name: str,
        message_id: str,
        raw_fields: dict[Any, Any],
    ) -> Entry | BadEntry:
        normalized = _normalize_stream_fields(raw_fields)

        actor_name = normalized.get("name")
        payload_raw = normalized.get("payload")
        if actor_name is None or payload_raw is None:
            return BadEntry(
                stream=stream,
                message_id=message_id,
                queue_name=queue_name,
                raw_fields=normalized,
                actor_name=actor_name,
                payload_raw=payload_raw,
                attempt=_safe_int(normalized.get("attempt", "0")),
                reason="字段缺失",
                error=ValueError("name / payload 字段缺失"),
            )

        attempt_raw = normalized.get("attempt", "0")
        try:
            attempt = int(attempt_raw)
        except (TypeError, ValueError) as error:
            return BadEntry(
                stream=stream,
                message_id=message_id,
                queue_name=queue_name,
                raw_fields=normalized,
                actor_name=actor_name,
                payload_raw=payload_raw,
                attempt=0,
                reason="attempt 字段非整数",
                error=error,
            )

        eta = _parse_eta(normalized.get("eta", ""))
        created_at = _safe_float(normalized.get("created_at", "0"))

        try:
            payload_envelope = decode_payload(payload_raw)
        except (json.JSONDecodeError, ValueError) as error:
            return BadEntry(
                stream=stream,
                message_id=message_id,
                queue_name=queue_name,
                raw_fields=normalized,
                actor_name=actor_name,
                payload_raw=payload_raw,
                attempt=attempt,
                reason="payload 解析失败",
                error=error,
            )

        binding = self.actor_for(queue_name, actor_name)
        if binding is None:
            return BadEntry(
                stream=stream,
                message_id=message_id,
                queue_name=queue_name,
                raw_fields=normalized,
                actor_name=actor_name,
                payload_raw=payload_raw,
                attempt=attempt,
                reason="actor 未注册",
                error=KeyError(f"actor 未注册: {actor_name}"),
            )

        return Entry(
            stream=stream,
            message_id=message_id,
            queue_name=queue_name,
            actor_name=actor_name,
            binding=binding,
            payload_envelope=payload_envelope,
            payload_raw=payload_raw,
            attempt=attempt,
            eta=eta,
            created_at=created_at,
        )

    def _calculate_eta(self, binding: ActorBinding, attempt: int) -> float:
        base_ms = binding.retry_backoff_ms_base
        max_ms = binding.retry_backoff_ms_max
        # attempt 来自消息字段，理论上由 worker 限制在 max_retries 范围；但消息也可能
        # 由外部 producer 直接构造，attempt 任意大会让 2**attempt 算出 megabyte 级 bignum。
        # 在左移前 saturating clamp 到 30——base * 2**30 ≈ 12 天，已远超任何合理 max_ms。
        shift = max(0, min(attempt, 30))
        backoff_ms = min(base_ms * (2**shift), max_ms)
        return time() + backoff_ms / 1000.0

    def _retry_and_ack(
        self,
        source_stream: str,
        queue_stream: str,
        message_id: str,
        retry_id: str,
        name: str,
        payload: str,
        attempt: int,
        eta: float,
        created_at: float,
    ) -> str:
        eta_text = str(eta)
        script = self._scripts.get("retry_and_ack")
        if script is not None:
            retry_stream_id = script(
                keys=[source_stream, queue_stream],
                args=[
                    self.group_name,
                    message_id,
                    retry_id,
                    name,
                    payload,
                    str(attempt),
                    eta_text,
                    str(created_at),
                ],
            )
            return _to_text(retry_stream_id)

        retry_stream_id = self.redis_client.xadd(
            queue_stream,
            cast(
                dict[Any, Any],
                {
                    "id": retry_id,
                    "name": name,
                    "payload": payload,
                    "attempt": str(attempt),
                    "eta": eta_text,
                    "created_at": str(created_at),
                },
            ),
        )
        self.redis_client.xack(source_stream, self.group_name, message_id)
        return _to_text(retry_stream_id)

    def _defer_and_ack(
        self,
        source_stream: str,
        queue_stream: str,
        message_id: str,
        defer_id: str,
        name: str,
        payload: str,
        attempt: int,
        eta: float,
        created_at: float,
    ) -> str:
        eta_text = str(eta)
        script = self._scripts.get("defer_and_ack")
        if script is not None:
            defer_stream_id = script(
                keys=[source_stream, queue_stream],
                args=[
                    self.group_name,
                    message_id,
                    defer_id,
                    name,
                    payload,
                    str(attempt),
                    eta_text,
                    str(created_at),
                ],
            )
            return _to_text(defer_stream_id)

        defer_stream_id = self.redis_client.xadd(
            queue_stream,
            cast(
                dict[Any, Any],
                {
                    "id": defer_id,
                    "name": name,
                    "payload": payload,
                    "attempt": str(attempt),
                    "eta": eta_text,
                    "created_at": str(created_at),
                },
            ),
        )
        self.redis_client.xack(source_stream, self.group_name, message_id)
        return _to_text(defer_stream_id)

    def _xq_and_ack(
        self,
        source_stream: str,
        group_name: str,
        message_id: str,
        xq_fields: dict[str, str],
    ) -> str:
        xq_stream = self.xq_stream_for()
        maxlen_arg = "" if self.xq_maxlen is None else str(self.xq_maxlen)
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
                    maxlen_arg,
                ],
            )
            return _to_text(xq_stream_id)

        if self.xq_maxlen is None:
            xq_stream_id = self.redis_client.xadd(
                xq_stream, cast(dict[Any, Any], xq_fields)
            )
        else:
            xq_stream_id = self.redis_client.xadd(
                xq_stream,
                cast(dict[Any, Any], xq_fields),
                maxlen=self.xq_maxlen,
                approximate=True,
            )
        self.redis_client.xack(source_stream, group_name, message_id)
        return _to_text(xq_stream_id)

    def _next_retry_message_id(self) -> str:
        return str(uuid4())

    def _mark_lua_degraded(self, reason: str) -> None:
        self._lua_degraded = True
        logger.warning(f"task_queue: {reason}")
        self.notify_hook("on_lua_degraded", reason)

    def notify_hook(self, name: str, *args: Any) -> None:
        """触发可观测性 hook，捕获回调抛出的异常以避免反向击穿 worker。

        BrokerOps Protocol 要求这是公共方法，worker 直接调用而不靠 getattr 反射。
        """
        callback = getattr(self.hooks, name, None)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as error:
            logger.warning(f"task_queue hook {name} 抛错被吞掉: {error}")


def calculate_namespace(worker: str, task: str) -> str:
    return f"{worker}:{{{task}}}"


def build_broker(
    redis_client: Redis | RedisCluster,
    namespace: str,
    group_name: str = "default",
    claim_idle_ms: int | None = None,
    xq_stream: str | None = None,
    xq_maxlen: int | None = None,
    hooks: BrokerHooks | None = None,
) -> TaskQueueBroker:
    if claim_idle_ms is not None and claim_idle_ms <= 0:
        raise ValueError("claim_idle_ms 必须大于 0")

    return TaskQueueBroker(
        redis_client=redis_client,
        namespace=namespace,
        group_name=group_name,
        claim_idle_ms=claim_idle_ms,
        xq_stream=xq_stream,
        xq_maxlen=xq_maxlen,
        hooks=hooks if hooks is not None else BrokerHooks(),
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

    normalized_payload = normalize_payload_envelope(payload, type(payload))
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


def send_messages(
    broker: TaskQueueBroker,
    messages: list[TaskMessage],
) -> list[ResultE[str]]:
    return broker.enqueue_many(messages)


def actor(
    broker: TaskQueueBroker,
    queue_name: str = "default",
    name: str | None = None,
    max_retries: int = 0,
    retry_backoff_ms_base: int = 1000,
    retry_backoff_ms_max: int = 60_000,
) -> Callable[[TaskHandler], RegisteredActor]:
    return broker.actor(
        queue_name=queue_name,
        name=name,
        max_retries=max_retries,
        retry_backoff_ms_base=retry_backoff_ms_base,
        retry_backoff_ms_max=retry_backoff_ms_max,
    )


# ----------------------------------------------------------------------
# 模块级纯函数（无 broker 状态依赖，方便单测）
# ----------------------------------------------------------------------


def _flatten_entries(response: Any) -> list[tuple[str, dict[Any, Any]]]:
    """把 xreadgroup 的返回值压平成 [(message_id, fields), ...]。

    兼容 redis-py < 5（外层 tuple）与 redis-py >= 5（外层 list）。
    """
    entries: list[tuple[str, dict[Any, Any]]] = []
    if not isinstance(response, list):
        return entries

    for stream_entries in response:
        if not isinstance(stream_entries, (list, tuple)):
            continue
        if len(stream_entries) != 2:
            continue
        _, items = stream_entries
        if not isinstance(items, list):
            continue
        for message_id, fields in items:
            entries.append((_to_text(message_id), fields))
    return entries


def _normalize_stream_fields(fields: dict[Any, Any]) -> dict[str, str]:
    return {_to_text(key): _to_text(value) for key, value in fields.items()}


def _parse_eta(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _client_supports_pipeline(client: Any) -> bool:
    pipeline = getattr(client, "pipeline", None)
    return callable(pipeline)
