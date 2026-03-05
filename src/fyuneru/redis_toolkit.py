"""
Redis 工具类
"""

from collections.abc import Callable
from functools import partial
from typing import Protocol

from redis import Redis, RedisCluster
from returns.result import safe


def init_client_standalone(
    host: str, port: int, db: int, **kwargs
) -> Callable[[], Redis]:
    return partial(Redis, host=host, port=port, db=db, **kwargs)


def init_client_cluster(
    host: str, port: int, **kwargs
) -> Callable[[], RedisCluster]:
    return partial(RedisCluster, host=host, port=port, **kwargs)


def calculate_checkpoint_key(
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


