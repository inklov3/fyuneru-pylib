from __future__ import annotations

from io import BytesIO

import fyuneru.worker.env as worker_env_module
from fyuneru.result import Success, unwrap
from fyuneru.worker import (
    calculate_checkpoint_key,
    calculate_result_key,
    setup_worker_env,
)


class FakeRedisClient:
    def __init__(self):
        self.sets: dict[str, set[str]] = {}

    def sadd(self, set_name: str, key: str) -> None:
        self.sets.setdefault(set_name, set()).add(key)

    def sismember(self, set_name: str, key: str) -> bool:
        return key in self.sets.get(set_name, set())


def test_calculate_keys() -> None:
    assert calculate_checkpoint_key("ws-a", "node-1") == "ws-a:checkpoint:node-1"
    assert (
        calculate_result_key("ws-a", "unit-1", "summary")
        == "ws-a/result/unit-1/summary.pkl"
    )


def test_setup_worker_env_without_optional_resources() -> None:
    env = setup_worker_env(
        label="node-1",
        config={},
        workspace="ws-a",
    )

    assert env.redis_client is None
    assert env.s3_writer is None
    assert env.s3_reader is None
    assert env.source_reader is None
    assert env.advance_checkpoint is None
    assert env.is_past_checkpoint is None


def test_setup_worker_env_with_all_resources() -> None:
    fake_redis = FakeRedisClient()
    written_data: dict[str, bytes] = {}

    from unittest.mock import patch

    with (
        patch.object(
            worker_env_module.redis_toolkit,
            "init_client_from_config",
            return_value=lambda: fake_redis,
        ),
        patch.object(
            worker_env_module.s3_toolkit,
            "init_client_from_config",
            return_value=lambda: object(),
        ),
        patch.object(
            worker_env_module.s3_toolkit,
            "bind_s3_writer",
            return_value=lambda key, body: Success(
                written_data.setdefault(key, body.read())
            ),
        ),
        patch.object(
            worker_env_module.s3_toolkit,
            "bind_s3_reader",
            return_value=lambda _key, consume: Success(consume(BytesIO(b"s3-data"))),
        ),
        patch.object(
            worker_env_module.s3_source,
            "load_source_registry",
            return_value={"src": {}},
        ),
        patch.object(
            worker_env_module.s3_source,
            "bind_source_reader",
            return_value=lambda _uri, consume: Success(
                consume(BytesIO(b"source-data"))
            ),
        ),
    ):
        env = setup_worker_env(
            label="node-1",
            config={
                "redis": {"host": "127.0.0.1", "port": 6379, "db": 0},
                "s3": {
                    "endpoint": "https://s3.example.com",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                    "bucket": "bucket-a",
                },
                "s3_sources": [],
            },
            workspace="ws-a",
        )

        assert env.redis_client is fake_redis
        assert env.s3_writer is not None
        assert env.s3_reader is not None
        assert env.source_reader is not None
        assert env.advance_checkpoint is not None
        assert env.is_past_checkpoint is not None

        unwrap(env.advance_checkpoint("item-1"))
        assert unwrap(env.is_past_checkpoint("item-1")) is True
        unwrap(env.s3_writer("foo", BytesIO(b"payload")))
        assert written_data["foo"] == b"payload"
        assert unwrap(env.s3_reader("foo", lambda body: body.read())) == b"s3-data"
        assert (
            unwrap(env.source_reader("blob://src/object-1", lambda body: body.read()))
            == b"source-data"
        )


if __name__ == "__main__":
    test_calculate_keys()
    test_setup_worker_env_without_optional_resources()
    test_setup_worker_env_with_all_resources()
    print("worker_env 测试通过")
