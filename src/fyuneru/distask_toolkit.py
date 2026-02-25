from collections.abc import Callable
from functools import partial
from typing import Any, cast

from dramatiq.broker import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.message import Message
from redis import Redis, RedisCluster


class RedisClusterLuaCompat:
    """
    RedisCluster 在执行 EVAL/EVALSHA/FCALL 时需要至少 1 个 key 才能路由到节点。
    当调用方给 numkeys=0（或 keys 为空）时，自动注入一个固定 routing_key。
    """

    def __init__(self, client: Redis | RedisCluster, routing_key: str) -> None:
        self._client = client
        self._routing_key = routing_key

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def _ensure_keys(
        self, numkeys: int, keys_and_args: tuple[Any, ...]
    ) -> tuple[int, tuple[Any, ...]]:
        if numkeys != 0:
            return numkeys, keys_and_args
        return 1, (self._routing_key, *keys_and_args)

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        n, kaa = self._ensure_keys(numkeys, keys_and_args)
        return self._client.eval(script, n, *kaa)

    def evalsha(self, sha: str, numkeys: int, *keys_and_args: Any) -> Any:
        n, kaa = self._ensure_keys(numkeys, keys_and_args)
        return self._client.evalsha(sha, n, *kaa)

    def fcall(self, func: str, numkeys: int, *keys_and_args: Any) -> Any:
        n, kaa = self._ensure_keys(numkeys, keys_and_args)
        return self._client.fcall(func, n, *kaa)

    def register_script(self, script: str) -> Callable[..., Any]:
        # Pyrefly 会抱怨 RedisCluster 不是 Redis 的 self；运行时通常没问题，这里显式 cast 一下。
        script_obj = cast(Redis, self._client).register_script(script)

        def _call(*args: Any, **kwargs: Any) -> Any:
            # 兼容 redis-py Script.__call__(keys=None, args=None, client=None, **kwargs)
            keys = kwargs.get("keys", None)
            if keys is None and args:
                keys = args[0]  # 仅在“确实有人用 positional keys”时才兜底

            if not keys:
                kwargs["keys"] = [self._routing_key]
                return script_obj(*args, **kwargs)

            return script_obj(*args, **kwargs)

        return _call


def calculate_namespace(worker: str, task: str) -> str:
    return f"{worker}:{{{task}}}"


def get_redis_broker(redis_client: Redis | RedisCluster, namespace: str) -> Broker:
    return RedisBroker(client=redis_client, namespace=namespace)


def new_message(
    actor_name: str,
    queue_name: str,
    args: tuple = (),
    kwargs: dict[str, Any] = {},
    options: dict = {},
) -> Message:
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
