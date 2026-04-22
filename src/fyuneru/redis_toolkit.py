"""
Redis 工具类
"""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Protocol

from redis import Redis, RedisCluster

from fyuneru.result import ResultE, safe

if TYPE_CHECKING:
    from redis import Redis, RedisCluster


def init_client_standalone(
    host: str, port: int, db: int, **kwargs
) -> Callable[[], Redis]:
    return partial(Redis, host=host, port=port, db=db, **kwargs)


def init_client_cluster(host: str, port: int, **kwargs) -> Callable[[], RedisCluster]:
    return partial(RedisCluster, host=host, port=port, **kwargs)


def init_client_from_config(
    config: dict,
) -> Callable[[], Redis] | Callable[[], RedisCluster]:
    """从配置构建 redis client initializer。

    config["redis"] 必须包含 host, port。可选: password, cluster, db。
    """
    redis_cfg = config["redis"]
    extra: dict = {}
    if "password" in redis_cfg:
        extra["password"] = redis_cfg["password"]
    if redis_cfg.get("cluster", False):
        return init_client_cluster(
            host=redis_cfg["host"], port=redis_cfg["port"], **extra
        )
    return init_client_standalone(
        host=redis_cfg["host"],
        port=redis_cfg["port"],
        db=redis_cfg.get("db", 0),
        **extra,
    )


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
