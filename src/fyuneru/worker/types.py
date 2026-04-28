from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fyuneru.result import ResultE

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.database import Database
    from redis import Redis, RedisCluster

    from fyuneru.s3_toolkit import ObjectStorageReader, ObjectStorageWriter


@dataclass(frozen=True)
class WorkerEnv:
    config: dict[str, Any]
    label: str
    redis_client: Redis | RedisCluster | None
    s3_writer: ObjectStorageWriter | None
    s3_reader: ObjectStorageReader | None
    source_reader: Callable[[str], ResultE[bytes]] | None
    mongo_db: Database | None
    advance_checkpoint: Callable[[str], ResultE[None]] | None
    is_past_checkpoint: Callable[[str], ResultE[bool]] | None
