from __future__ import annotations

from time import time
from typing import Any

from fyuneru.result import ResultE, safe
from fyuneru.task_queue.actor import build_xq_fields
from fyuneru.task_queue.codec import decode_payload, encode_payload


@safe
def run_worker(
    broker: Any,
    queue_name: str = "default",
    consumer_name: str = "worker-1",
    block_ms: int = 1000,
    max_messages: int | None = None,
    stop_when_idle: bool = False,
) -> int:
    processed = 0
    stream = broker._stream_name(queue_name)
    broker._ensure_group(stream)

    while True:
        if max_messages is not None and processed >= max_messages:
            break

        claimed = broker._claim_entries(stream, consumer_name)
        entries = claimed
        if not entries:
            response = broker.redis_client.xreadgroup(
                groupname=broker.group_name,
                consumername=consumer_name,
                streams={stream: ">"},
                count=1,
                block=block_ms,
            )
            entries = broker._flatten_entries(response)

        if not entries:
            if stop_when_idle:
                break
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
            if max_messages is not None and processed >= max_messages:
                break

    return processed


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
    payload = decode_payload(payload_raw)
    attempt = int(normalized.get("attempt", "0"))

    actors = broker._actors.get(queue_name, {})
    actor = actors.get(actor_name)
    if actor is None:
        raise KeyError(f"actor 未注册: {actor_name}")

    try:
        actor(payload)
        broker.redis_client.xack(stream, broker.group_name, message_id)
    except Exception as error:
        _handle_failure(
            broker=broker,
            stream=stream,
            queue_name=queue_name,
            message_id=message_id,
            actor_name=actor_name,
            payload=payload,
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
