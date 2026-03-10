from collections.abc import Callable
from functools import partial

from pymongo import MongoClient
from pymongo.database import Database


def init_client(
    uri: str, timeout: int = 1000 * 10, db: str | None = None
) -> Callable[[], MongoClient] | Callable[[], Database]:
    """
    构建 MongoClient 惰性初始化器。
    若指定 db，调用返回值将直接返回对应的 Database 而非裸 MongoClient。
    """
    factory = partial(MongoClient, host=uri, serverSelectionTimeoutMS=timeout)
    if db is None:
        return factory
    return lambda: factory()[db]
