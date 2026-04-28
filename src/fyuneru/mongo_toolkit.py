from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from pymongo import MongoClient

from fyuneru.result import ResultE, safe

if TYPE_CHECKING:
    from pymongo.collection import Collection
    from pymongo.database import Database


def init_client(uri: str, timeout: int = 1000 * 10) -> Callable[[], MongoClient]:
    """构建 MongoClient 惰性初始化器。"""
    return partial(MongoClient, host=uri, serverSelectionTimeoutMS=timeout)


def init_client_from_config(config: dict) -> Callable[[], MongoClient]:
    """从配置构建 mongo client initializer。

    config["mongo"] 必须包含 uri。可选: timeout。
    """
    mongo_cfg = config["mongo"]
    kwargs: dict = {"uri": mongo_cfg["uri"]}
    if "timeout" in mongo_cfg:
        kwargs["timeout"] = mongo_cfg["timeout"]
    return init_client(**kwargs)


def init_database_from_config(config: dict) -> Callable[[], Database]:
    """从配置构建 MongoDB Database initializer。

    config["mongo"] 必须包含 uri, db。可选: timeout。
    """
    mongo_cfg = config["mongo"]
    init = init_client(
        uri=mongo_cfg["uri"],
        **({} if "timeout" not in mongo_cfg else {"timeout": mongo_cfg["timeout"]}),
    )
    db = mongo_cfg["db"]
    return lambda: init()[db]


def bind_collection(db: Database, name: str) -> Collection:
    if not isinstance(name, str):
        raise TypeError("collection 名称必须是字符串")
    normalized_name = name.strip()
    if normalized_name == "":
        raise ValueError("collection 名称不能为空")
    return db[normalized_name]


@safe
def ensure_index(
    collection: Collection,
    name: str,
    keys: list[tuple[str, int]],
    unique: bool = False,
    sparse: bool = False,
    background: bool = True,
) -> str:
    if not isinstance(name, str):
        raise TypeError("索引名称必须是字符串")
    normalized_name = name.strip()
    if normalized_name == "":
        raise ValueError("索引名称不能为空")
    if not isinstance(keys, list) or not keys:
        raise ValueError("keys 必须是非空列表")

    normalized_keys: list[tuple[str, int]] = []
    for item in keys:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError("keys 元素必须是 (字段名, 方向) 二元组")
        field, direction = item
        if not isinstance(field, str) or field.strip() == "":
            raise ValueError("索引字段名必须是非空字符串")
        if not isinstance(direction, int):
            raise ValueError("索引方向必须是 int")
        normalized_keys.append((field, direction))

    existing_indexes = collection.index_information()
    if normalized_name in existing_indexes:
        existing = existing_indexes[normalized_name]
        existing_keys = existing.get("key")
        existing_unique = bool(existing.get("unique", False))
        existing_sparse = bool(existing.get("sparse", False))

        if existing_keys is None:
            raise ValueError(f"索引 {normalized_name} 缺少 key 定义")
        if list(existing_keys) != normalized_keys:
            raise ValueError(f"索引 {normalized_name} 的 keys 与期望不一致")
        if existing_unique != unique:
            raise ValueError(f"索引 {normalized_name} 的 unique 与期望不一致")
        if existing_sparse != sparse:
            raise ValueError(f"索引 {normalized_name} 的 sparse 与期望不一致")
        return normalized_name

    return str(
        collection.create_index(
            normalized_keys,
            name=normalized_name,
            unique=unique,
            sparse=sparse,
            background=background,
        )
    )
