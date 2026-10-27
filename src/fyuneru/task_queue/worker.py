import os
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


def _default_consumer_name() -> str:
    """未显式指定 consumer_name 时的回退策略。

    K8s 下注入的 HOSTNAME 即 Pod 名（如 ``task-worker-7d9f8b-x4k2p``），
    本地裸跑时为机器主机名。两种场景都自然唯一，且 ``XINFO CONSUMERS``
    里直接可读，免去手动传 ``--consumer "$(POD_NAME)"`` 的负担。
    缺省（极端裸环境）才退回到固定 ``worker-1``。
    """
    hostname = os.environ.get("HOSTNAME", "").strip()
    return hostname or "worker-1"


def run_worker(
    broker: BrokerOps,
    queue_name: str = "default",
    consumer_name: str | None = None,
    block_ms: int = 1000,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """阻塞消费 ``queue_name`` 上的消息，直到 ``should_stop()`` 返回 True。

    设计要点：
    - **per-message 异常隔离**：handler / broker.handle_xq_for_entry 自身抛错
      都不会让 worker 退出，仅记录日志并跳过。
    - **Redis 连接错误隔离**：``read_entries`` 把 ConnectionError / TimeoutError
      转成 ``ReadOutcome.redis_error``，worker 在此做指数 backoff。
    - **graceful shutdown**：``should_stop`` 由调用方注入（库不夺取 SIGTERM）。

    返回值为已成功 ACK（含 xq）的消息数量。
    """
    if consumer_name is None:
        consumer_name = _default_consumer_name()

    stream = broker.stream_for(queue_name)
    broker.ensure_group(stream)

    processed = 0
    redis_error_streak = 0

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

        for bad in outcome.bad_entries:
            _safely(
                broker.handle_xq_for_bad,
                bad,
                description=f"handle_xq_for_bad({bad.message_id})",
            )
            processed += 1

        for entry in outcome.entries:
            _dispatch(broker, entry)
            processed += 1


def run_worker_once_for_test(
    broker: BrokerOps,
    queue_name: str = "default",
    consumer_name: str | None = None,
    block_ms: int = 1,
) -> int:
    """单次循环版的 worker，仅用于测试。

    返回值含义同 ``run_worker``：本轮处理（执行 / xq）的消息数量。
    """
    if consumer_name is None:
        consumer_name = _default_consumer_name()

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
        _dispatch(broker, entry)
        processed += 1
    return processed


def _dispatch(broker: BrokerOps, entry: Entry) -> None:
    """对单条 Entry 执行 handler，并把成功 / xq 两种路径都护好。"""
    broker.notify_hook("on_handle_start", entry.queue_name)

    try:
        handler_payload = decode_for_handler_payload(
            entry.payload_envelope, entry.binding.payload_type
        )
    except Exception as error:
        # payload 与 dataclass 不匹配——直接进 xq。
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
        elapsed,
    )


def _safely(
    operation: Callable[..., object],
    *args: object,
    description: str,
) -> None:
    """执行 broker 写操作，吞掉所有异常并 warning。

    任何对 Redis 的写操作（xack / xadd / xq）都可能在 Redis 故障期间
    抛错，但 worker 不应因此退出——失败的消息会留在 PEL 里，可由
    claim_idle_ms + xautoclaim 救回。
    """
    try:
        operation(*args)
    except Exception as error:
        logger.warning(f"task_queue: {description} 抛错被吞掉: {error}")
