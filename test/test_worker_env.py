from __future__ import annotations

from dataclasses import dataclass

from fyuneru.mongo_toolkit import bind_collection, ensure_index
from fyuneru.result import Failure, Success, is_failure, is_success, unwrap
from fyuneru.worker import calculate_checkpoint_key, calculate_result_key, setup_worker_env
import fyuneru.worker.env as worker_env_module


class FakeRedisClient:
    def __init__(self):
        self.sets: dict[str, set[str]] = {}

    def sadd(self, set_name: str, key: str) -> None:
        self.sets.setdefault(set_name, set()).add(key)

    def sismember(self, set_name: str, key: str) -> bool:
        return key in self.sets.get(set_name, set())


class FakeCollection:
    def __init__(self):
        self.indexes: dict[str, dict] = {"_id_": {}}
        self.create_calls: list[tuple[list[tuple[str, int]], str, bool, bool, bool]] = []

    def index_information(self) -> dict[str, dict]:
        return self.indexes

    def create_index(
        self,
        keys: list[tuple[str, int]],
        name: str,
        unique: bool,
        sparse: bool,
        background: bool,
    ) -> str:
        self.create_calls.append((keys, name, unique, sparse, background))
        self.indexes[name] = {}
        return name


class FakeDatabase:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def test_calculate_keys() -> None:
    assert calculate_checkpoint_key("ws-a", "etl", "node-1") == "ws-a:etl:checkpoint:node-1"
    assert (
        calculate_result_key("ws-a", "media-1", "node-1", "summary")
        == "ws-a/media-1/results/node-1/summary.pkl"
    )


def test_setup_worker_env_without_optional_resources() -> None:
    env = setup_worker_env(
        label="node-1",
        config={
            "workspace": "ws-a",
            "task": "etl",
        },
    )

    assert env.redis_client is None
    assert env.s3_writer is None
    assert env.s3_reader is None
    assert env.source_reader is None
    assert env.mongo_db is None
    assert env.advance_checkpoint is None
    assert env.is_past_checkpoint is None


def test_setup_worker_env_with_all_resources() -> None:
    fake_redis = FakeRedisClient()
    fake_db = FakeDatabase()

    original_configure_logger = worker_env_module.configure_logger
    original_redis_init = worker_env_module.redis_toolkit.init_client_from_config
    original_s3_init = worker_env_module.s3_toolkit.init_client_from_config
    original_bind_s3_writer = worker_env_module.s3_toolkit.bind_s3_writer
    original_bind_s3_reader = worker_env_module.s3_toolkit.bind_s3_reader
    original_load_registry = worker_env_module.s3_source.load_source_registry
    original_bind_source_reader = worker_env_module.s3_source.bind_source_reader
    original_mongo_init_db = worker_env_module.mongo_toolkit.init_database_from_config

    try:
        worker_env_module.configure_logger = lambda level="INFO", log_dir=None: Success(None)
        worker_env_module.redis_toolkit.init_client_from_config = (
            lambda _config: lambda: fake_redis
        )
        worker_env_module.s3_toolkit.init_client_from_config = lambda _config: lambda: object()
        worker_env_module.s3_toolkit.bind_s3_writer = (
            lambda _client, _bucket: lambda _key, _body: Success(None)
        )
        worker_env_module.s3_toolkit.bind_s3_reader = (
            lambda _client, _bucket: lambda _key: Success(b"s3-data")
        )
        worker_env_module.s3_source.load_source_registry = lambda _config: {"src": {}}
        worker_env_module.s3_source.bind_source_reader = (
            lambda _registry: lambda _uri: Success(b"source-data")
        )
        worker_env_module.mongo_toolkit.init_database_from_config = (
            lambda _config: lambda: fake_db
        )

        env = setup_worker_env(
            label="node-1",
            config={
                "workspace": "ws-a",
                "task": "etl",
                "redis": {"host": "127.0.0.1", "port": 6379, "db": 0},
                "s3": {
                    "endpoint": "https://s3.example.com",
                    "access_key_id": "ak",
                    "secret_access_key": "sk",
                    "bucket": "bucket-a",
                },
                "s3_sources": [],
                "mongo": {"uri": "mongodb://127.0.0.1:27017", "db": "db-a"},
            },
        )

        assert env.redis_client is fake_redis
        assert env.s3_writer is not None
        assert env.s3_reader is not None
        assert env.source_reader is not None
        assert env.mongo_db is fake_db
        assert env.advance_checkpoint is not None
        assert env.is_past_checkpoint is not None

        unwrap(env.advance_checkpoint("item-1"))
        assert unwrap(env.is_past_checkpoint("item-1")) is True
        assert unwrap(env.s3_reader("foo")) == b"s3-data"
        assert unwrap(env.source_reader("blob://src/object-1")) == b"source-data"
    finally:
        worker_env_module.configure_logger = original_configure_logger
        worker_env_module.redis_toolkit.init_client_from_config = original_redis_init
        worker_env_module.s3_toolkit.init_client_from_config = original_s3_init
        worker_env_module.s3_toolkit.bind_s3_writer = original_bind_s3_writer
        worker_env_module.s3_toolkit.bind_s3_reader = original_bind_s3_reader
        worker_env_module.s3_source.load_source_registry = original_load_registry
        worker_env_module.s3_source.bind_source_reader = original_bind_source_reader
        worker_env_module.mongo_toolkit.init_database_from_config = original_mongo_init_db


def test_bind_collection_and_ensure_index() -> None:
    db = FakeDatabase()
    collection = bind_collection(db, "items")

    first = ensure_index(
        collection,
        "idx_media_key",
        [("media_key", 1)],
        unique=True,
        sparse=False,
        background=True,
    )
    assert is_success(first)
    assert isinstance(first, Success)
    assert first.value == "idx_media_key"
    assert len(collection.create_calls) == 1

    second = ensure_index(
        collection,
        "idx_media_key",
        [("media_key", 1)],
    )
    assert is_success(second)
    assert len(collection.create_calls) == 1


def test_ensure_index_rejects_invalid_keys() -> None:
    collection = FakeCollection()
    result = ensure_index(collection, "idx_invalid", [])
    assert is_failure(result)
    assert isinstance(result, Failure)
    assert "keys 必须是非空列表" in str(result.error)


if __name__ == "__main__":
    test_calculate_keys()
    test_setup_worker_env_without_optional_resources()
    test_setup_worker_env_with_all_resources()
    test_bind_collection_and_ensure_index()
    test_ensure_index_rejects_invalid_keys()
    print("worker_env 测试通过")
