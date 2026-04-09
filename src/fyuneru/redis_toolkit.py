"""
Redis 工具类
"""

from collections.abc import Callable
from functools import partial
from typing import Protocol

from redis import Redis, RedisCluster
from returns.result import ResultE, safe


def init_client_standalone(
    host: str, port: int, db: int, **kwargs
) -> Callable[[], Redis]:
    return partial(Redis, host=host, port=port, db=db, **kwargs)


def init_client_cluster(host: str, port: int, **kwargs) -> Callable[[], RedisCluster]:
    return partial(RedisCluster, host=host, port=port, **kwargs)


def calculate_checkpoint_key(checkpoint: str, task: str, worker: str) -> str:
    return f"{worker}:{task}:checkpoint:{checkpoint}"


class RedisSetReader(Protocol):
    def __call__(self, key: str) -> ResultE[bool]: ...


class RedisSetWriter(Protocol):
    def __call__(self, key: str) -> ResultE[None]: ...


class RedisSetDeleter(Protocol):
    def __call__(self, key: str) -> ResultE[None]: ...


def bind_redis_set_writer(
    client: Redis | RedisCluster,
    set_name: str,
) -> RedisSetWriter:
    @safe
    def set_writer(key: str) -> None:
        client.sadd(set_name, key)

    return set_writer


def bind_redis_set_reader(
    client: Redis | RedisCluster,
    set_name: str,
) -> RedisSetReader:
    @safe
    def set_reader(key: str) -> bool:
        result = client.sismember(set_name, key)
        return bool(result)

    return set_reader


def bind_redis_set_deleter(
    client: Redis | RedisCluster,
    set_name: str,
) -> RedisSetDeleter:
    @safe
    def set_deleter(key: str) -> None:
        client.srem(set_name, key)

    return set_deleter
