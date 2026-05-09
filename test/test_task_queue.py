from __future__ import annotations

from dataclasses import dataclass

from fyuneru.result import Failure, Success, is_failure, is_success
from fyuneru.task_queue import (
    actor,
    build_broker,
    calculate_namespace,
    new_message,
    send_messages,
)
from fyuneru.task_queue.actor import resolve_payload_type
from fyuneru.task_queue.worker import run_worker_once_for_test


class FakeScript:
    def __init__(self, client: FakeRedisClient, script_name: str):
        self.client = client
        self.script_name = script_name

    def __call__(self, keys: list[str], args: list[str]):
        if self.script_name == "retry_and_ack":
            source_stream, queue_stream = keys
            (
                group_name,
                message_id,
                retry_id,
                name,
                payload,
                attempt,
                eta,
                created_at,
            ) = args
            retry_stream_id = self.client.xadd(
                queue_stream,
                {
                    "id": retry_id,
                    "name": name,
                    "payload": payload,
                    "attempt": attempt,
                    "eta": eta,
                    "created_at": created_at,
                },
            )
            self.client.xack(source_stream, group_name, message_id)
            return retry_stream_id

        if self.script_name == "xq_and_ack":
            source_stream, xq_stream = keys
            (
                group_name,
                message_id,
                original_id,
                queue_name,
                name,
                payload,
                attempt,
                error,
                traceback,
                failed_at,
            ) = args
            xq_stream_id = self.client.xadd(
                xq_stream,
                {
                    "original_id": original_id,
                    "queue": queue_name,
                    "name": name,
                    "payload": payload,
                    "attempt": attempt,
                    "error": error,
                    "traceback": traceback,
                    "failed_at": failed_at,
                },
            )
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

    def register_script(self, script: str) -> FakeScript:
        if self.fail_register_script:
            raise RuntimeError("register_script failed")
        if "retry_stream_id" in script:
            return FakeScript(self, "retry_and_ack")
        if "xq_stream_id" in script:
            return FakeScript(self, "xq_and_ack")
        raise ValueError("unknown script content")

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self._counter += 1
        message_id = f"{self._counter}-0"
        self.stream_entries.setdefault(stream, []).append((message_id, fields))
        return message_id

    def xgroup_create(self, name: str, groupname: str, id: str, mkstream: bool) -> None:
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


def test_task_queue_send_and_consume_success_dataclass() -> None:
    namespace = calculate_namespace(worker="worker-a", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    called: list[Payload] = []

    @actor(
        broker,
        queue_name="default",
        name="process_item",
    )
    def process_item(payload: Payload) -> None:
        called.append(payload)

    send_result = process_item.send(Payload(item_id="item-1", priority=3))

    assert is_success(send_result)
    worker_result = run_worker_once_for_test(broker, queue_name="default")
    assert is_success(worker_result)
    assert isinstance(worker_result, Success)
    assert worker_result.value == 1
    assert called == [Payload(item_id="item-1", priority=3)]


def test_task_queue_failure_goes_to_xq_when_no_retry() -> None:
    namespace = calculate_namespace(worker="worker-b", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default", name="always_fail")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    message = new_message(
        name="always_fail",
        queue_name="default",
        payload=Payload(item_id="item-2", priority=1),
    )
    send_result = broker.enqueue(message)
    assert isinstance(send_result, str)

    worker_result = run_worker_once_for_test(broker, queue_name="default")
    assert is_success(worker_result)

    xq_stream = f"{namespace}:xq"
    xq_entries = redis_client.stream_entries.get(xq_stream, [])
    assert len(xq_entries) == 1
    xq_fields = xq_entries[0][1]
    assert xq_fields["name"] == "always_fail"
    assert xq_fields["attempt"] == "0"
    assert xq_fields["original_id"] == "1-0"


def test_task_queue_retry_uses_atomic_script() -> None:
    namespace = calculate_namespace(worker="worker-d", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default", name="fail_once", max_retries=1)
    def fail_once(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("retry")

    broker.enqueue(
        new_message(
            name="fail_once",
            queue_name="default",
            payload=Payload(item_id="item-3", priority=2),
        )
    )
    result = run_worker_once_for_test(broker, queue_name="default")
    assert is_success(result)

    stream = f"{namespace}:default"
    entries = redis_client.stream_entries[stream]
    assert len(entries) == 2
    retried_fields = entries[1][1]
    assert retried_fields["attempt"] == "1"
    assert retried_fields["name"] == "fail_once"


def test_task_queue_lua_fallback_without_register_script() -> None:
    namespace = calculate_namespace(worker="worker-e", task="etl")
    redis_client = FakeRedisClient()
    redis_client.fail_register_script = True
    broker = build_broker(redis_client, namespace=namespace)

    @actor(broker, queue_name="default", name="always_fail")
    def always_fail(payload: Payload) -> None:
        _ = payload
        raise RuntimeError("boom")

    broker.enqueue(
        new_message(
            name="always_fail",
            queue_name="default",
            payload=Payload(item_id="item-4", priority=0),
        )
    )
    result = run_worker_once_for_test(broker, queue_name="default")
    assert is_success(result)

    xq_stream = f"{namespace}:xq"
    assert len(redis_client.stream_entries.get(xq_stream, [])) == 1


def test_claim_entries_accepts_list_response() -> None:
    namespace = calculate_namespace(worker="worker-f", task="etl")
    redis_client = FakeRedisClient()
    redis_client.autoclaim_returns_list = True
    broker = build_broker(
        redis_client,
        namespace=namespace,
        claim_idle_ms=500,
    )

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "name": "noop",
            "payload": "{}",
            "attempt": "0",
            "eta": "",
            "created_at": "0",
        },
    )

    claimed = broker._claim_entries(stream, consumer_name="worker-1")
    assert len(claimed) == 1


def test_actor_send_rejects_wrong_payload_dataclass_type() -> None:
    namespace = calculate_namespace(worker="worker-g", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(
        broker,
        queue_name="default",
        name="process_item",
    )
    def process_item(payload: Payload) -> None:
        _ = payload

    result = process_item.send({"item_id": "item-1", "priority": 3})
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "payload 类型必须与函数注解 dataclass 一致" in str(result.error)


def test_worker_failfast_on_payload_type_mismatch() -> None:
    namespace = calculate_namespace(worker="worker-h", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    @actor(
        broker,
        queue_name="default",
        name="process_item",
    )
    def process_item(payload: Payload) -> None:
        _ = payload

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "name": "process_item",
            "payload": '{"payload_type": "dict", "payload": {"item_id": "x", "priority": 1}}',
            "attempt": "0",
            "eta": "",
            "created_at": "0",
        },
    )

    result = run_worker_once_for_test(broker, queue_name="default")
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "payload_type 不匹配" in str(result.error)


def test_new_message_rejects_non_dataclass_payload() -> None:
    try:
        new_message(
            name="task", queue_name="default", payload={"item_id": "x", "priority": 1}
        )
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


def test_actor_rejects_negative_max_retries() -> None:
    namespace = calculate_namespace(worker="worker-i", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    try:
        actor(broker, queue_name="default", name="bad", max_retries=-1)
        assert False, "应抛出 ValueError"
    except ValueError as error:
        assert "max_retries 不能小于 0" in str(error)


def test_run_worker_returns_failure_for_invalid_message_payload() -> None:
    namespace = calculate_namespace(worker="worker-c", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    stream = f"{namespace}:default"
    redis_client.xadd(
        stream,
        {
            "id": "msg-1",
            "name": "unknown",
            "payload": "[]",
            "attempt": "0",
            "eta": "",
            "created_at": "0",
        },
    )

    result = run_worker_once_for_test(broker, queue_name="default")
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "payload 必须是对象映射" in str(result.error)


def test_send_messages_batch_success() -> None:
    namespace = calculate_namespace(worker="worker-j", task="etl")
    redis_client = FakeRedisClient()
    broker = build_broker(redis_client, namespace=namespace)

    messages = [
        new_message(
            name="process_item",
            queue_name="default",
            payload=Payload(item_id="item-1", priority=1),
        ),
        new_message(
            name="process_item",
            queue_name="default",
            payload=Payload(item_id="item-2", priority=2),
        ),
    ]

    results = send_messages(broker, messages)
    assert len(results) == 2
    assert all(is_success(item) for item in results)


if __name__ == "__main__":
    test_task_queue_send_and_consume_success_dataclass()
    test_task_queue_failure_goes_to_xq_when_no_retry()
    test_task_queue_retry_uses_atomic_script()
    test_task_queue_lua_fallback_without_register_script()
    test_claim_entries_accepts_list_response()
    test_actor_send_rejects_wrong_payload_dataclass_type()
    test_worker_failfast_on_payload_type_mismatch()
    test_new_message_rejects_non_dataclass_payload()
    test_register_actor_rejects_non_dataclass_annotation()
    test_register_actor_rejects_missing_annotation()
    test_register_actor_rejects_multiple_payload_parameters()
    test_actor_rejects_negative_max_retries()
    test_run_worker_returns_failure_for_invalid_message_payload()
    test_send_messages_batch_success()
    print("task_queue 测试通过")
