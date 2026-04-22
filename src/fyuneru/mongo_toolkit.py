from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from pymongo import MongoClient

if TYPE_CHECKING:
    from pymongo import MongoClient
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
