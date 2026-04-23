from __future__ import annotations

from typing import Any

from dramatiq.broker import Broker
from dramatiq.message import Message
from redis import Redis, RedisCluster


def calculate_namespace(worker: str, task: str) -> str:
    return f"{worker}:{{{task}}}"


def build_broker(redis_client: Redis | RedisCluster, namespace: str) -> Broker:
    from dramatiq.brokers.redis import RedisBroker

    return RedisBroker(client=redis_client, namespace=namespace)


def new_message(
    actor_name: str,
    queue_name: str,
    args: tuple = (),
    kwargs: dict[str, Any] | None = None,
    options: dict | None = None,
) -> Message:
    if kwargs is None:
        kwargs = {}
    if options is None:
        options = {}
    return Message(
        queue_name=queue_name,
        actor_name=actor_name,
        kwargs=kwargs,
        options=options,
        args=args,
    )


def send_message(
    broker: Broker,
    message: Message,
) -> Message:
    return broker.enqueue(message)
