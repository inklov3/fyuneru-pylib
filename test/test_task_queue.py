from __future__ import annotations

import json
from dataclasses import dataclass

from fyuneru.result import Failure, Success, is_failure, is_success
from fyuneru.task_queue import (
    BrokerHooks,
    actor,
    build_broker,
    new_message,
)
from fyuneru.task_queue.actor import resolve_payload_type
from fyuneru.task_queue.broker import _flatten_entries
from fyuneru.task_queue.worker import run_worker_once_for_test


class FakeScript:
    def __init__(self, client: FakeRedisClient, script_name: str):
        self.client = client
        self.script_name = script_name

    def __call__(self, keys: list[str], args: list[str]):
        if self.script_name == "xq_and_ack":
            source_stream, xq_stream = keys
            (
                group_name,
                message_id,
                original_id,
                queue_name,
                payload,
                error,
                traceback,
                failed_at,
                xq_maxlen,
            ) = args
            fields = {
                "original_id": original_id,
                "queue": queue_name,
                "payload": payload,
                "error": error,
                "traceback": traceback,
                "failed_at": failed_at,
            }
            if xq_maxlen != "":
                xq_stream_id = self.client.xadd(
                    xq_stream, fields, maxlen=int(xq_maxlen)
                )
            else:
                xq_stream_id = self.client.xadd(xq_stream, fields)
            self.client.xack(source_stream, group_name, message_id)
            return xq_stream_id

        raise ValueError(f"unknown script: {self.script_name}")


class FakeRedisClient:
    def __init__(self):
        self.stream_entries: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.pending: dict[tuple[str, str], list[str]] = {}
        self.delivered: dict[tuple[str, str], set[str]] = {}
        self.acked: list[tuple[str, str, str]] = []
        self.groups: set[tuple[str, str]] = set()
        self._counter = 0
        self.fail_register_script = False
        self.autoclaim_returns_list = False
        self.xreadgroup_returns_list = False

    def register_script(self, script: str) -> FakeScript:
        if self.fail_register_script:
            raise RuntimeError("register_script failed")
        if "xq_stream_id" in script:
            return FakeScript(self, "xq_and_ack")
        raise ValueError("unknown script content")

    def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        _ = approximate
        self._counter += 1
        message_id = f"{self._counter}-0"
        entries = self.stream_entries.setdefault(stream, [])
        entries.append((message_id, fields))
        if maxlen is not None and len(entries) > maxlen:
            del entries[: len(entries) - maxlen]
        return message_id

    def xgroup_create(
        self, name: str, groupname: str, id: str, mkstream: bool
    ) -> None:
        self.groups.add((name, groupname))
        self.stream_entries.setdefault(name, [])

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int,
        block: int,
    ):
        _ = consumername, count, block
        stream = next(iter(streams.keys()))
        entries = self.stream_entries.get(stream, [])
        group_key = (stream, groupname)
        pending_ids = self.pending.setdefault(group_key, [])
        delivered_ids = self.delivered.setdefault(group_key, set())

        for message_id, _fields in entries:
            if message_id not in delivered_ids:
                delivered_ids.add(message_id)
                pending_ids.append(message_id)
                for entry_id, entry_fields in entries:
                    if entry_id == message_id:
                        # 默认 list 形态（redis-py 5+）；可显式切到 tuple 测兼容
                        if self.xreadgroup_returns_list:
                            return [[stream, [(entry_id, entry_fields)]]]
                        return [(stream, [(entry_id, entry_fields)])]

        return []

    def xack(self, stream: str, groupname: str, message_id: str) -> int:
        group_key = (stream, groupname)
        pending_ids = self.pending.setdefault(group_key, [])
        if message_id in pending_ids:
            pending_ids.remove(message_id)
            self.acked.append((stream, groupname, message_id))
            return 1
        return 0

    def xautoclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        start_id: str,
        count: int,
    ):
        _ = groupname, consumername, min_idle_time, start_id, count
        entries = self.stream_entries.get(name, [])
        if not entries:
            empty = ["0-0", [], []]
            if self.autoclaim_returns_list:
                return empty
            return tuple(empty)

        message_id, fields = entries[0]
        claimed = ["0-0", [(message_id, fields)], []]
        if self.autoclaim_returns_list:
            return claimed
        return tuple(claimed)


@dataclass(frozen=True)
class Payload:
    item_id: str
    priority: int


# ----------------------------------------------------------------------
# 基本投递 / 消费
# ----------------------------------------------------------------------


def test_task_queue_send_and_consume_success_dataclass() -> None:
    namespace = "worker-a:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    called: list[Payload] = []

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        called.append(payload)

    send_result = process_item.send(Payload(item_id="item-1", priority=3))
    assert is_success(send_result)

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1
    assert called == [Payload(item_id="item-1", priority=3)]


def test_send_messages_batch_success() -> None:
    namespace = "worker-j:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    messages = [
        new_message(
            queue_name="default",
            payload=Payload(item_id=f"item-{i}", priority=i),
        )
        for i in range(3)
    ]

    results = broker.enqueue_many(messages)
    assert len(results) == 3
    assert all(is_success(item) for item in results)


# ----------------------------------------------------------------------
# 失败 → xq / 重试
# ----------------------------------------------------------------------


def test_task_queue_failure_goes_to_xq_when_no_retry() -> None:
    namespace = "worker-b:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    broker.enqueue(
        new_message(
            queue_name="default",
            payload=Payload(item_id="item-2", priority=1),
        )
    )

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1

    xq_stream = f"{namespace}:xq"
    xq_entries = redis_client.stream_entries.get(xq_stream, [])
    assert len(xq_entries) == 1
    xq_fields = xq_entries[0][1]
    assert "name" not in xq_fields
    assert "attempt" not in xq_fields
    assert xq_fields["original_id"] == "1-0"


def test_task_queue_lua_fallback_without_register_script() -> None:
    namespace = "worker-e:{etl}"
    redis_client = FakeRedisClient()
    redis_client.fail_register_script = True
    broker = build_broker(redis_client, namespace=namespace)
    assert broker._lua_degraded is True

    @actor(broker, queue_name="default")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    broker.enqueue(
        new_message(
            queue_name="default",
            payload=Payload(item_id="item-4", priority=0),
        )
    )
    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1

    xq_stream = f"{namespace}:xq"
    xq_entries = redis_client.stream_entries.get(xq_stream, [])
    assert len(xq_entries) == 1
    assert "attempt" not in xq_entries[0][1]


# ----------------------------------------------------------------------
# 坏消息：解码失败 / actor 未注册 / 字段错误
# ----------------------------------------------------------------------


def test_bad_payload_goes_to_xq_without_killing_worker() -> None:
    namespace = "worker-h:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        _ = payload

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "payload": '{"payload_type": "dict", "payload": {"item_id": "x", "priority": 1}}',
            "created_at": "0",
        },
    )

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1

    xq_stream = f"{namespace}:xq"
    assert len(redis_client.stream_entries.get(xq_stream, [])) == 1


def test_unknown_queue_goes_to_xq() -> None:
    namespace = "worker-c:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "payload": '{"payload_type": "x.Y", "payload": {}}',
            "created_at": "0",
        },
    )

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1

    xq_stream = f"{namespace}:xq"
    xq_entries = redis_client.stream_entries.get(xq_stream, [])
    assert len(xq_entries) == 1
    assert "queue 未注册 actor" in xq_entries[0][1]["error"]


def test_invalid_json_payload_goes_to_xq() -> None:
    namespace = "worker-c2:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "payload": "not-json",
            "created_at": "0",
        },
    )

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1
    xq_stream = f"{namespace}:xq"
    assert len(redis_client.stream_entries.get(xq_stream, [])) == 1


def test_handler_raise_does_not_kill_worker() -> None:
    """连续两条会让 handler 抛错的消息，worker 必须都成功送到 xq。"""
    namespace = "worker-k:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    for i in range(2):
        broker.enqueue(
            new_message(
                queue_name="default",
                payload=Payload(item_id=f"item-{i}", priority=i),
            )
        )

    for _ in range(2):
        run_worker_once_for_test(broker, queue_name="default")

    xq_stream = f"{namespace}:xq"
    assert len(redis_client.stream_entries.get(xq_stream, [])) == 2


# ----------------------------------------------------------------------
# _flatten_entries 兼容 list / tuple
# ----------------------------------------------------------------------


def test_flatten_entries_accepts_tuple_outer() -> None:
    response = [("stream-a", [("1-0", {"k": "v"})])]
    entries = _flatten_entries(response)
    assert entries == [("1-0", {"k": "v"})]


def test_flatten_entries_accepts_list_outer() -> None:
    response = [["stream-a", [("1-0", {"k": "v"})]]]
    entries = _flatten_entries(response)
    assert entries == [("1-0", {"k": "v"})]


def test_worker_consumes_with_list_xreadgroup_response() -> None:
    namespace = "worker-listmode:{etl}"
    redis_client = FakeRedisClient()
    redis_client.xreadgroup_returns_list = True
    broker = build_broker(redis_client, namespace=namespace)

    called: list[Payload] = []

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        called.append(payload)

    process_item.send(Payload(item_id="item-1", priority=1))

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1
    assert called == [Payload(item_id="item-1", priority=1)]


# ----------------------------------------------------------------------
# claim_idle_ms 路径（list 返回的 xautoclaim）
# ----------------------------------------------------------------------


def test_claim_entries_accepts_list_response() -> None:
    namespace = "worker-f:{etl}"
    redis_client = FakeRedisClient()
    redis_client.autoclaim_returns_list = True
    broker = build_broker(redis_client, namespace=namespace, claim_idle_ms=500)

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "payload": "{}",
            "created_at": "0",
        },
    )

    claimed = broker._claim_entries(stream, consumer_name="worker-1")
    assert len(claimed) == 1


# ----------------------------------------------------------------------
# 投递端校验（producer 仍是 fail-fast）
# ----------------------------------------------------------------------


def test_actor_send_rejects_wrong_payload_dataclass_type() -> None:
    namespace = "worker-g:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        _ = payload

    result = process_item.send({"item_id": "item-1", "priority": 3})
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "payload 类型必须与函数注解 dataclass 一致" in str(result.error)


def test_new_message_rejects_non_dataclass_payload() -> None:
    try:
        new_message(queue_name="default", payload={"item_id": "x", "priority": 1})
        assert False, "应抛出 TypeError"
    except TypeError as error:
        assert "payload_type 必须是 dataclass" in str(error)


def test_register_actor_rejects_non_dataclass_annotation() -> None:
    def bad(payload: int) -> None:
        _ = payload

    try:
        resolve_payload_type(bad)
        assert False, "应抛出 TypeError"
    except TypeError as error:
        assert "payload 参数类型必须是 dataclass" in str(error)


def test_register_actor_rejects_missing_annotation() -> None:
    def bad(payload) -> None:
        _ = payload

    try:
        resolve_payload_type(bad)
        assert False, "应抛出 TypeError"
    except TypeError as error:
        assert "payload 参数必须声明 dataclass 类型注解" in str(error)


def test_register_actor_rejects_multiple_payload_parameters() -> None:
    def bad(payload: Payload, extra: Payload) -> None:
        _ = payload, extra

    try:
        resolve_payload_type(bad)
        assert False, "应抛出 TypeError"
    except TypeError as error:
        assert "actor 函数必须且仅能声明一个 payload 参数" in str(error)


def test_register_duplicate_actor_for_same_queue_raises() -> None:
    """同一 queue 注册第二个 actor 应立即 fail-fast。"""
    namespace = "worker-dup:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default")
    def first(payload: Payload) -> None:
        _ = payload

    try:

        @actor(broker, queue_name="default")
        def second(payload: Payload) -> None:
            _ = payload

        assert False, "应抛出 ValueError"
    except ValueError as error:
        assert "queue 已注册 actor: default" in str(error)


# ----------------------------------------------------------------------
# Hooks
# ----------------------------------------------------------------------


def test_hooks_fired_on_success_path() -> None:
    namespace = "worker-hooks:{etl}"
    redis_client = FakeRedisClient()

    starts: list[str] = []
    successes: list[str] = []
    enqueues: list[str] = []

    hooks = BrokerHooks(
        on_handle_start=lambda q: starts.append(q),
        on_handle_success=lambda q, e: successes.append(q),
        on_enqueue=lambda q: enqueues.append(q),
    )
    broker = build_broker(redis_client, namespace=namespace, hooks=hooks)

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        _ = payload

    process_item.send(Payload(item_id="x", priority=1))
    run_worker_once_for_test(broker, queue_name="default")

    assert enqueues == ["default"]
    assert starts == ["default"]
    assert successes == ["default"]


def test_hooks_fired_on_xq() -> None:
    namespace = "worker-hookr:{etl}"
    redis_client = FakeRedisClient()

    xqs: list[str] = []
    hooks = BrokerHooks(
        on_handle_xq=lambda q, e: xqs.append(q),
    )
    broker = build_broker(redis_client, namespace=namespace, hooks=hooks)

    @actor(broker, queue_name="default")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    broker.enqueue(
        new_message(
            queue_name="default",
            payload=Payload(item_id="x", priority=1),
        )
    )

    run_worker_once_for_test(broker, queue_name="default")

    assert xqs == ["default"]


def test_hook_exception_does_not_break_worker() -> None:
    namespace = "worker-hbreak:{etl}"
    redis_client = FakeRedisClient()

    def bad_hook(*args):
        raise RuntimeError("hook 坏掉")

    hooks = BrokerHooks(on_handle_success=bad_hook)
    broker = build_broker(redis_client, namespace=namespace, hooks=hooks)

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        _ = payload

    process_item.send(Payload(item_id="x", priority=1))
    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1


def test_lua_degraded_triggers_hook() -> None:
    namespace = "worker-luah:{etl}"
    redis_client = FakeRedisClient()
    redis_client.fail_register_script = True

    reasons: list[str] = []
    hooks = BrokerHooks(on_lua_degraded=lambda r: reasons.append(r))
    broker = build_broker(redis_client, namespace=namespace, hooks=hooks)

    assert broker._lua_degraded is True
    assert len(reasons) == 1
    assert "Lua" in reasons[0]


# ----------------------------------------------------------------------
# Redis 连接错误隔离
# ----------------------------------------------------------------------


def test_read_entries_returns_redis_error_outcome() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    namespace = "worker-conn:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    def boom(*args, **kwargs):
        raise RedisConnectionError("挂了")

    redis_client.xreadgroup = boom  # type: ignore[assignment]

    outcome = broker.read_entries(
        stream=f"{namespace}:default",
        queue_name="default",
        consumer_name="w-1",
        block_ms=1,
    )
    assert outcome.redis_error is not None
    assert isinstance(outcome.redis_error, RedisConnectionError)
    assert outcome.entries == []
    assert outcome.bad_entries == []


def test_should_stop_terminates_run_worker() -> None:
    from fyuneru.task_queue.worker import run_worker

    namespace = "worker-stop:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    processed = run_worker(
        broker=broker,
        queue_name="default",
        consumer_name="worker-1",
        block_ms=1,
        should_stop=lambda: True,
    )
    assert processed == 0


# ----------------------------------------------------------------------
# enqueue_many pipeline 路径
# ----------------------------------------------------------------------


def test_enqueue_many_uses_pipeline_when_available() -> None:
    namespace = "worker-pipe:{etl}"

    class PipelineFakeRedis(FakeRedisClient):
        def __init__(self):
            super().__init__()
            self.pipeline_calls = 0

        def pipeline(self, transaction: bool = True):
            self.pipeline_calls += 1
            return FakePipeline(self)

    class FakePipeline:
        def __init__(self, client: PipelineFakeRedis):
            self.client = client
            self.ops: list[tuple[str, dict]] = []

        def xadd(self, stream: str, fields: dict):
            self.ops.append((stream, fields))

        def execute(self, raise_on_error: bool = True):
            ids = []
            for stream, fields in self.ops:
                ids.append(self.client.xadd(stream, fields))
            return ids

    redis_client = PipelineFakeRedis()
    broker = build_broker(redis_client, namespace=namespace)

    messages = [
        new_message(
            queue_name="default",
            payload=Payload(item_id=f"i-{i}", priority=i),
        )
        for i in range(5)
    ]
    results = broker.enqueue_many(messages)
    assert len(results) == 5
    assert all(is_success(item) for item in results)
    assert redis_client.pipeline_calls == 1


# ----------------------------------------------------------------------
# xq_maxlen
# ----------------------------------------------------------------------


def test_xq_maxlen_trims_failed_messages() -> None:
    namespace = "worker-maxlen:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace, xq_maxlen=3)

    @actor(broker, queue_name="default")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    for i in range(10):
        broker.enqueue(
            new_message(
                queue_name="default",
                payload=Payload(item_id=f"i-{i}", priority=i),
            )
        )

    for _ in range(10):
        run_worker_once_for_test(broker, queue_name="default")

    xq_stream = f"{namespace}:xq"
    assert len(redis_client.stream_entries.get(xq_stream, [])) == 3


# ----------------------------------------------------------------------
# 新语义验证：失败直接进 XQ，无重试
# ----------------------------------------------------------------------


def test_handler_failure_goes_straight_to_xq() -> None:
    """handler 首次失败立即进 XQ，live stream 无重投递副本。"""
    namespace = "worker-straight-xq:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("直接进 xq")

    broker.enqueue(
        new_message(queue_name="default", payload=Payload(item_id="x", priority=1))
    )

    stream = f"{namespace}:default"
    entries_before = len(redis_client.stream_entries.get(stream, []))

    run_worker_once_for_test(broker, queue_name="default")

    # live stream 没有新副本（原始消息已 ACK，无重试写回）
    entries_after = len(redis_client.stream_entries.get(stream, []))
    assert entries_after == entries_before

    xq_stream = f"{namespace}:xq"
    xq_entries = redis_client.stream_entries.get(xq_stream, [])
    assert len(xq_entries) == 1
    assert "直接进 xq" in xq_entries[0][1]["error"]


def test_legacy_message_with_attempt_and_eta_fields_is_consumed() -> None:
    """旧版消息携带 attempt/eta 字段时，新 worker 静默忽略并正常 dispatch。"""
    namespace = "worker-legacy:{etl}"
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    called: list[Payload] = []

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        called.append(payload)

    payload_obj = Payload(item_id="legacy-x", priority=5)
    envelope = json.dumps(
        {
            "payload_type": f"{Payload.__module__}.{Payload.__qualname__}",
            "payload": {"item_id": "legacy-x", "priority": 5},
        }
    )
    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "legacy-msg-1",
            "payload": envelope,
            "attempt": "3",
            "eta": "999999999",
            "created_at": "0",
        },
    )

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1
    # handler 被正常调用，消息未被当作 BadEntry
    assert called == [payload_obj]
    # 没有 XQ 条目
    xq_stream = f"{namespace}:xq"
    assert len(redis_client.stream_entries.get(xq_stream, [])) == 0


def test_idle_message_reclaimed_then_handled() -> None:
    """XAUTOCLAIM 接管的 idle 消息走 dispatch 路径，成功 ACK 或失败进 XQ。"""
    namespace = "worker-autoclaim:{etl}"
    redis_client = FakeRedisClient()
    redis_client.autoclaim_returns_list = True
    broker = build_broker(redis_client, namespace=namespace, claim_idle_ms=500)

    called: list[Payload] = []

    @actor(broker, queue_name="default")
    def process_item(payload: Payload) -> None:
        called.append(payload)

    payload_obj = Payload(item_id="claim-item", priority=1)
    envelope = json.dumps(
        {
            "payload_type": f"{Payload.__module__}.{Payload.__qualname__}",
            "payload": {"item_id": "claim-item", "priority": 1},
        }
    )
    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "claim-msg-1",
            "payload": envelope,
            "created_at": "0",
        },
    )

    processed = run_worker_once_for_test(broker, queue_name="default")
    assert processed == 1
    assert called == [payload_obj]


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------


if __name__ == "__main__":
    test_task_queue_send_and_consume_success_dataclass()
    test_send_messages_batch_success()
    test_task_queue_failure_goes_to_xq_when_no_retry()
    test_task_queue_lua_fallback_without_register_script()
    test_bad_payload_goes_to_xq_without_killing_worker()
    test_unknown_queue_goes_to_xq()
    test_invalid_json_payload_goes_to_xq()
    test_handler_raise_does_not_kill_worker()
    test_flatten_entries_accepts_tuple_outer()
    test_flatten_entries_accepts_list_outer()
    test_worker_consumes_with_list_xreadgroup_response()
    test_claim_entries_accepts_list_response()
    test_actor_send_rejects_wrong_payload_dataclass_type()
    test_new_message_rejects_non_dataclass_payload()
    test_register_actor_rejects_non_dataclass_annotation()
    test_register_actor_rejects_missing_annotation()
    test_register_actor_rejects_multiple_payload_parameters()
    test_register_duplicate_actor_for_same_queue_raises()
    test_hooks_fired_on_success_path()
    test_hooks_fired_on_xq()
    test_hook_exception_does_not_break_worker()
    test_lua_degraded_triggers_hook()
    test_read_entries_returns_redis_error_outcome()
    test_should_stop_terminates_run_worker()
    test_enqueue_many_uses_pipeline_when_available()
    test_xq_maxlen_trims_failed_messages()
    test_handler_failure_goes_straight_to_xq()
    test_legacy_message_with_attempt_and_eta_fields_is_consumed()
    test_idle_message_reclaimed_then_handled()
    print("task_queue 测试通过")
