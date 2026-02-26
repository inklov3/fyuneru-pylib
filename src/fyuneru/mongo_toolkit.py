from pymongo import MongoClient


def create_client(uri: str, timeout: int = 1000 * 10) -> MongoClient:
    return MongoClient(host=uri, serverSelectionTimeoutMS=timeout)
