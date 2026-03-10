from collections.abc import Callable
from functools import partial

from pymongo import MongoClient


def init_client(uri: str, timeout: int = 1000 * 10) -> Callable[[], MongoClient]:
    """构建 MongoClient 惰性初始化器。"""
    return partial(MongoClient, host=uri, serverSelectionTimeoutMS=timeout)
