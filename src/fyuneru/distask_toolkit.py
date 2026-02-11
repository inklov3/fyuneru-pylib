from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dramatiq.broker import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.message import Message
from redis import Redis, RedisCluster


class _RedisClusterLuaCompat:
    """
    RedisCluster 在执行 EVAL/EVALSHA/FCALL 时需要至少 1 个 key 用于路由到具体节点。
    一些上层库会在脚本调用里传 numkeys=0（或 keys=[]），会直接触发：
      redis.exceptions.ResponseError: for redis cluster,
      eval/evalsha/fcall number of keys can't be zero

    这里用一个“路由 key”兜底：当调用方不给 key 时，自动注入 1 个固定 key。
    """

    def __init__(self, client: RedisCluster, routing_key: str) -> None:
        self._client = client
        self._routing_key = routing_key

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        if numkeys == 0:
            return self._client.eval(script, 1, self._routing_key, *keys_and_args)
        return self._client.eval(script, numkeys, *keys_and_args)

    def evalsha(self, sha: str, numkeys: int, *keys_and_args: Any) -> Any:
        if numkeys == 0:
            return self._client.evalsha(sha, 1, self._routing_key, *keys_and_args)
        return self._client.evalsha(sha, numkeys, *keys_and_args)

    def fcall(self, func: str, numkeys: int, *keys_and_args: Any) -> Any:
        if numkeys == 0:
            return self._client.fcall(func, 1, self._routing_key, *keys_and_args)
        return self._client.fcall(func, numkeys, *keys_and_args)

    def register_script(self, script: str):
        script_obj = self._client.register_script(script)

        def _call(*args: Any, **kwargs: Any) -> Any:
            # redis-py Script.__call__ 通常是：script(keys=None, args=None, client=None, **kwargs)
            keys = kwargs.get("keys")
            if keys is None and len(args) >= 1:
                # 兼容脚本对象的 positional：第一个参数通常是 keys
                keys = args[0]

            if not keys:
                kwargs["keys"] = [self._routing_key]
                return script_obj(**kwargs)

            return script_obj(*args, **kwargs)

        return _call


def init_redis_broker(
    redis_getter: Callable[[], Redis | RedisCluster],
    namespace: str = "znk:{dramatiq}",
) -> Callable[[], Broker]:
    redis_client = redis_getter()
    if isinstance(redis_client, RedisCluster):
        # 兜底路由 key：复用 namespace 的 hash tag（如 "{dramatiq}"）可以保证路由稳定
        routing_key = f"{namespace}:__lua_route__"
        redis_client = _RedisClusterLuaCompat(redis_client, routing_key=routing_key)
    # middleware = WorkflowMiddleware(backend=MemcachedBackend())
    redis_broker = RedisBroker(client=redis_client, namespace=namespace)
    # redis_broker.add_middleware(middleware)

    def get_redis_broker() -> Broker:
        return redis_broker

    return get_redis_broker


def init_redis_cluster_broker(
    redis_cluster_getter: Callable[[], RedisCluster],
) -> Callable[[], Broker]:
    redis_cluster = redis_cluster_getter()
    redis_cluster_broker = RedisBroker(
        client=redis_cluster, namespace="inklov3:{dramatiq}"
    )

    def get_redis_cluster_broker() -> Broker:
        return redis_cluster_broker

    return get_redis_cluster_broker


def new_message(
    actor_name: str,
    queue_name: str,
    kwargs: dict[str, any],
    options: dict | None = None,
    args: list | None = None,
) -> Message:
    if not args:
        args = ()
    if not options:
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
    actor_name: str,
    queue_name: str,
    kwargs: dict[str, any],
    options: dict | None = None,
    args: list | None = None,
) -> Message:
    msg = new_message(actor_name, queue_name, kwargs, options, args)
    return broker.enqueue(msg)
