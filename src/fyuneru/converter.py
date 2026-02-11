"""数据转化器"""

from io import BytesIO
from pickle import dump as dump_pickle
from pickle import load as load_pickle
from typing import Any


def object_to_bytes(data: Any) -> bytes:
    buf = BytesIO()
    dump_pickle(data, buf)
    buf.seek(0)
    return buf.getvalue()


def bytes_to_object(data: bytes) -> Any:
    buf = BytesIO(data)
    buf.seek(0)
    return load_pickle(buf)


class NonSerializable:
    """
    序列化忽略标记
    """

    def __repr__(self):
        return "<NonSerializable>"


def to_json_object(data: Any) -> Any:
    """
    转 json 对象
    """
    if data is None:
        return None
    if isinstance(data, (str, int, float, bool)):
        return data
    # 先处理namedtuple
    if callable(getattr(data, "_asdict", None)):
        return to_json_object(data._asdict())
    if isinstance(data, (list, tuple, set)):
        return [to_json_object(v) for v in data if not isinstance(v, NonSerializable)]
    if isinstance(data, dict):
        return {
            str(k): to_json_object(v)
            for k, v in data.items()
            if not isinstance(v, NonSerializable)
        }
    if hasattr(data, "__dict__"):
        filtered = {
            str(k): v
            for k, v in vars(data).items()
            if not isinstance(v, NonSerializable)
        }
        return to_json_object(filtered)
    raise TypeError(f"Unsupported serialization type: {type(data)}")
