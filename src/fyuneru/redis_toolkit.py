"""
Redis 工具类
"""

from collections.abc import Callable
from functools import partial
from typing import Protocol

from redis import Redis, RedisCluster
from returns.result import safe


class AdvanceCheckpoint(Protocol):
    @safe
    def __call__(self, checkpoint_uid: str) -> None: ...


class IsPastCheckpoint(Protocol):
    @safe
    def __call__(self, checkpoint_uid: str) -> bool: ...


class DelCheckpoint(Protocol):
    @safe
    def __call__(self, checkpoint_uid: str) -> None: ...


def init_client_standalone(
    host: str, port: int, db: int, **kwargs
) -> Callable[[], Redis]:
    return partial(Redis, host=host, port=port, db=db, **kwargs)


def init_client_cluster(
    host: str, port: int, **kwargs
) -> Callable[[], RedisCluster]:
    return partial(RedisCluster, host=host, port=port, **kwargs)


def checkpoint_calculator(
    checkpoint: str, task: str, worker: str
) -> str:
    return f"{worker}:{task}:checkpoint:{checkpoint}"


class RedisSetReader(Protocol):
    @safe
    def __call__(self, key: str) -> bool: ...


class RedisSetWriter(Protocol):
    @safe
    def __call__(self, key: str) -> None: ...


class RedisSetDeleter(Protocol):
    @safe
    def __call__(self, key: str) -> None: ...


def gen_redis_set(
    client: Redis | RedisCluster, set_name: str
) -> tuple[RedisSetWriter, RedisSetReader, RedisSetDeleter]:
    @safe
    def set_writer(key: str) -> None:
        client.sadd(set_name, key)

    @safe
    def set_reader(key: str) -> bool:
        result = client.sismember(set_name, key)
        return bool(result)

    @safe
    def set_deleter(key: str) -> None:
        client.srem(set_name, key)

    return set_writer, set_reader, set_deleter


def gen_checkpointer(
    client: Redis | RedisCluster,
    checkpoint: str,
    task: str,
    worker: str,
) -> tuple[AdvanceCheckpoint, IsPastCheckpoint, DelCheckpoint]:
    checkpoint_id = checkpoint_calculator(
        checkpoint, task, worker
    )
    set_writer, set_reader, set_deleter = gen_redis_set(
        client, checkpoint_id
    )

    @safe
    def advance_checkpoint(checkpoint_uid: str) -> None:
        set_writer(checkpoint_uid).unwrap()

    @safe
    def is_past_checkpoint(checkpoint_uid: str) -> bool:
        return set_reader(checkpoint_uid).unwrap()

    @safe
    def del_checkpoint(checkpoint_uid: str) -> None:
        set_deleter(checkpoint_uid).unwrap()

    return advance_checkpoint, is_past_checkpoint, del_checkpoint
