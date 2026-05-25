from __future__ import annotations

from collections.abc import Callable
from time import sleep, time
from typing import TYPE_CHECKING

from loguru import logger

from fyuneru.task_queue.codec import decode_for_handler_payload
from fyuneru.task_queue.protocols import Entry

if TYPE_CHECKING:
    from fyuneru.task_queue.protocols import BrokerOps


_REDIS_ERROR_SLEEP_BASE = 0.5
_REDIS_ERROR_SLEEP_MAX = 30.0
# defer-only 批次的最大单次睡眠。睡到 min(remaining_eta, block_ms) 而不是固定 100ms，
# 避免 "每 100ms 复制一份 + XACK" 的 hot loop。上限由 block_ms 提供，保证 should_stop
# 在不超过 block_ms 内被回检。
_DEFER_SLEEP_FALLBACK = 0.1


def run_worker(
    broker: BrokerOps,
    queue_name: str = "default",
    consumer_name: str = "worker-1",
    block_ms: int = 1000,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """阻塞消费 ``queue_name`` 上的消息，直到 ``should_stop()`` 返回 True。

    设计要点：
    - **per-message 异常隔离**：handler / broker.handle_retry / broker.handle_xq_for_entry
      自身抛错都不会让 worker 退出，仅记录日志并跳过。
    - **Redis 连接错误隔离**：``read_entries`` 把 ConnectionError / TimeoutError
      转成 ``ReadOutcome.redis_error``，worker 在此做指数 backoff。
    - **graceful shutdown**：``should_stop`` 由调用方注入（库不夺取 SIGTERM）。

    返回值为已成功 ACK（含 retry / xq）的消息数量。
    """
    stream = broker.stream_for(queue_name)
    broker.ensure_group(stream)

    processed = 0
    redis_error_streak = 0
    block_seconds = max(block_ms, 0) / 1000.0

    while True:
        if should_stop is not None and should_stop():
            return processed

        outcome = broker.read_entries(
            stream=stream,
            queue_name=queue_name,
            consumer_name=consumer_name,
            block_ms=block_ms,
        )

        if outcome.redis_error is not None:
            sleep_seconds = min(
                _REDIS_ERROR_SLEEP_BASE * (2**redis_error_streak),
                _REDIS_ERROR_SLEEP_MAX,
            )
            redis_error_streak += 1
            logger.warning(
                "task_queue: Redis 读取失败，{:.1f}s 后重试: {}".format(
                    sleep_seconds, outcome.redis_error
                )
            )
            sleep(sleep_seconds)
            continue
        redis_error_streak = 0

        deferred_only = bool(outcome.entries) and not outcome.bad_entries
        any_executed = False
        min_remaining: float | None = None

        for bad in outcome.bad_entries:
            _safely(
                broker.handle_xq_for_bad,
                bad,
                description=f"handle_xq_for_bad({bad.message_id})",
            )
            processed += 1

        for entry in outcome.entries:
            now = time()
            if entry.eta is not None and entry.eta > now:
                _safely(
                    broker.handle_defer,
                    entry,
                    description=f"handle_defer({entry.message_id})",
                )
                remaining = entry.eta - now
                if min_remaining is None or remaining < min_remaining:
                    min_remaining = remaining
                continue

            deferred_only = False
            _dispatch(broker, entry)
            any_executed = True
            processed += 1

        if deferred_only and not any_executed:
            # 睡到最早 eta（或 block_ms 上限）。block_ms 充当 should_stop 的回检粒度，
            # 同时给新消息一个进入流的窗口；min_remaining 缺省时退回到旧的 100ms。
            if min_remaining is not None:
                sleep_seconds = min(min_remaining, block_seconds or _DEFER_SLEEP_FALLBACK)
            else:
                sleep_seconds = _DEFER_SLEEP_FALLBACK
            if sleep_seconds > 0:
                sleep(sleep_seconds)


def run_worker_once_for_test(
    broker: BrokerOps,
    queue_name: str = "default",
    consumer_name: str = "worker-1",
    block_ms: int = 1,
) -> int:
    """单次循环版的 worker，仅用于测试。

    返回值含义同 ``run_worker``：本轮处理（执行 / xq / defer）的消息数量。
    """
    stream = broker.stream_for(queue_name)
    broker.ensure_group(stream)

    outcome = broker.read_entries(
        stream=stream,
        queue_name=queue_name,
        consumer_name=consumer_name,
        block_ms=block_ms,
    )

    if outcome.redis_error is not None:
        logger.warning(
            "task_queue: Redis 读取失败 (test-once): {}".format(outcome.redis_error)
        )
        return 0

    processed = 0
    for bad in outcome.bad_entries:
        _safely(
            broker.handle_xq_for_bad,
            bad,
            description=f"handle_xq_for_bad({bad.message_id})",
        )
        processed += 1

    for entry in outcome.entries:
        now = time()
        if entry.eta is not None and entry.eta > now:
            _safely(
                broker.handle_defer,
                entry,
                description=f"handle_defer({entry.message_id})",
            )
            processed += 1
            continue
        _dispatch(broker, entry)
        processed += 1
    return processed


def _dispatch(broker: BrokerOps, entry: Entry) -> None:
    """对单条 Entry 执行 handler，并把成功 / 重试 / xq 三种路径都护好。"""
    broker.notify_hook(
        "on_handle_start", entry.queue_name, entry.actor_name, entry.attempt
    )

    try:
        handler_payload = decode_for_handler_payload(
            entry.payload_envelope, entry.binding.payload_type
        )
    except Exception as error:
        # payload 与 dataclass 不匹配，重试也救不了——直接进 xq。
        _safely(
            broker.handle_xq_for_entry,
            entry,
            error,
            description=f"handle_xq_for_entry({entry.message_id}) [bad payload]",
        )
        return

    started = time()
    try:
        entry.binding.handler(handler_payload)
    except Exception as handler_error:
        if entry.attempt < entry.binding.max_retries:
            _safely(
                broker.handle_retry,
                entry,
                handler_error,
                description=f"handle_retry({entry.message_id})",
            )
            return
        _safely(
            broker.handle_xq_for_entry,
            entry,
            handler_error,
            description=f"handle_xq_for_entry({entry.message_id})",
        )
        return

    elapsed = time() - started
    _safely(
        broker.handle_success,
        entry,
        description=f"handle_success({entry.message_id})",
    )
    broker.notify_hook(
        "on_handle_success",
        entry.queue_name,
        entry.actor_name,
        entry.attempt,
        elapsed,
    )


def _safely(
    operation: Callable[..., object],
    *args: object,
    description: str,
) -> None:
    """执行 broker 写操作，吞掉所有异常并 warning。

    任何对 Redis 的写操作（xack / xadd / retry / xq）都可能在 Redis 故障期间
    抛错，但 worker 不应因此退出——失败的消息会留在 PEL 里，可由
    claim_idle_ms + xautoclaim 救回。
    """
    try:
        operation(*args)
    except Exception as error:
        logger.warning(f"task_queue: {description} 抛错被吞掉: {error}")
