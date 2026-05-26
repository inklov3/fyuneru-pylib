# fyuneru.converter

pickle 字节互转、任意对象转 JSON 兼容结构。默认安装。

## API

```python
from fyuneru.converter import (
    unsafe_object_to_bytes,
    unsafe_bytes_to_object,
    to_json_object,
    NonSerializable,
)

unsafe_object_to_bytes(data: Any) -> bytes    # pickle.dumps
unsafe_bytes_to_object(data: bytes) -> Any    # pickle.loads

to_json_object(data: Any) -> Any
# 递归转 JSON 兼容结构。
# 支持：primitives、namedtuples、list/tuple/set/frozenset、dict、有 __dict__ 的对象，
#       以及 datetime/date/time (isoformat)、Decimal/UUID/PurePath (str)、
#       bytes/bytearray (base64 ascii)。
# NonSerializable 标记的字段会被排除。
# 不支持的类型抛 TypeError。
```

## 关键约束

- `unsafe_*` 前缀是刻意的：**pickle.loads 对外部输入等于 RCE**。只用于完全可信的内部字节流（同进程内多 worker 共享、自己写入的 cache 等）。在 grep 时这个 `unsafe_` 前缀就是给 reviewer 的红旗。
- 跨网络/跨信任边界传输请用 `to_json_object` + json 序列化，不要 pickle
