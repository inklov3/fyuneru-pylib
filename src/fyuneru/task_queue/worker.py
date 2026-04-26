from __future__ import annotations

from time import time
from typing import Any

from fyuneru.result import ResultE, safe
from fyuneru.task_queue.actor import build_xq_fields
from fyuneru.task_queue.codec import (
    decode_for_handler_payload,
    decode_payload,
    encode_payload,
)


@safe
def run_worker(
    broker: Any,
    queue_name: str = "default",
    consumer_name: str = "worker-1",
    block_ms: int = 1000,
) -> int:
    processed = 0
    stream = broker._stream_name(queue_name)
    broker._ensure_group(stream)

    while True:
        entries = _read_entries(
            broker=broker,
            stream=stream,
            consumer_name=consumer_name,
            block_ms=block_ms,
        )
        if not entries:
            continue

        for message_id, fields in entries:
            _process_message(
                broker=broker,
                stream=stream,
                queue_name=queue_name,
                message_id=message_id,
                fields=fields,
            )
            processed += 1

    return processed


@safe
def run_worker_once_for_test(
    broker: Any,
    queue_name: str = "default",
    consumer_name: str = "worker-1",
    block_ms: int = 1,
) -> int:
    stream = broker._stream_name(queue_name)
    broker._ensure_group(stream)

    entries = _read_entries(
        broker=broker,
        stream=stream,
        consumer_name=consumer_name,
        block_ms=block_ms,
    )
    if not entries:
        return 0

    processed = 0
    for message_id, fields in entries:
        _process_message(
            broker=broker,
            stream=stream,
            queue_name=queue_name,
            message_id=message_id,
            fields=fields,
        )
        processed += 1
    return processed


def _read_entries(
    broker: Any,
    stream: str,
    consumer_name: str,
    block_ms: int,
) -> list[tuple[str, dict[Any, Any]]]:
    claimed = broker._claim_entries(stream, consumer_name)
    if claimed:
        return claimed

    response = broker.redis_client.xreadgroup(
        groupname=broker.group_name,
        consumername=consumer_name,
        streams={stream: ">"},
        count=1,
        block=block_ms,
    )
    return broker._flatten_entries(response)


def _process_message(
    broker: Any,
    stream: str,
    queue_name: str,
    message_id: str,
    fields: dict[Any, Any],
) -> None:
    normalized = broker._normalize_stream_fields(fields)
    actor_name = normalized["name"]
    payload_raw = normalized["payload"]
    payload_envelope = decode_payload(payload_raw)
    attempt = int(normalized.get("attempt", "0"))

    actors = broker._actors.get(queue_name, {})
    binding = actors.get(actor_name)
    if binding is None:
        raise KeyError(f"actor 未注册: {actor_name}")

    handler_payload = decode_for_handler_payload(payload_envelope, binding.payload_type)

    try:
        binding.handler(handler_payload)
        broker.redis_client.xack(stream, broker.group_name, message_id)
    except Exception as error:
        _handle_failure(
            broker=broker,
            stream=stream,
            queue_name=queue_name,
            message_id=message_id,
            actor_name=actor_name,
            payload=payload_envelope,
            attempt=attempt,
            error=error,
        )


def _handle_failure(
    broker: Any,
    stream: str,
    queue_name: str,
    message_id: str,
    actor_name: str,
    payload: dict[str, Any],
    attempt: int,
    error: Exception,
) -> None:
    payload_str = encode_payload(payload)

    if attempt < broker.max_retries:
        retry_message_id = broker._next_retry_message_id()
        broker._retry_and_ack(
            source_stream=stream,
            queue_stream=broker._stream_name(queue_name),
            group_name=broker.group_name,
            message_id=message_id,
            retry_id=retry_message_id,
            name=actor_name,
            payload=payload_str,
            attempt=attempt + 1,
            created_at=time(),
        )
        return

    xq_fields = build_xq_fields(
        original_id=message_id,
        queue_name=queue_name,
        actor_name=actor_name,
        payload=payload_str,
        attempt=attempt,
        error=error,
        failed_at=time(),
    )
    broker._xq_and_ack(
        source_stream=stream,
        xq_stream=broker._xq_stream_name(),
        group_name=broker.group_name,
        message_id=message_id,
        xq_fields=xq_fields,
    )
