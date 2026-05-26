# fyuneru.mongo_toolkit

MongoClient 惰性初始化与按配置获取 `Database`。

需要：`fyuneru[mongo]`

## API

```python
from fyuneru.mongo_toolkit import (
    init_client,
    init_client_from_config,
    init_database_from_config,
    bind_collection,
    ensure_index,
)

init_client(uri: str, timeout: int = 10000) -> Callable[[], MongoClient]
# timeout 是 serverSelectionTimeoutMS。

init_client_from_config(config: dict) -> Callable[[], MongoClient]
# 读 config["mongo"]。缺段抛 KeyError。

init_database_from_config(config: dict) -> Callable[[], Database]
# 读 config["mongo"]，必须含 "db" 字段。

bind_collection(db: Database, name: str) -> Collection
# 返回 db[name]，附带名称校验。

ensure_index(
    collection: Collection,
    name: str,
    keys: list[tuple[str, int]],
    unique: bool = False,
    sparse: bool = False,
    background: bool = True,
) -> ResultE[str]
# 缺索引时创建。
# 同名索引已存在但 keys/unique/sparse 与预期不一致时返回 Failure (冲突错误)。
```

## 关键约束

- `init_database_from_config` 强制要 `mongo.db`；只要 client 用 `init_client_from_config`
- `ensure_index` 不会自动 drop+recreate 冲突索引；冲突时返回 Failure，由调用方决定如何处理
