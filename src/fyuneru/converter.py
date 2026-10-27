"""数据转化器"""

from base64 import b64encode
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from pathlib import PurePath
from pickle import dump as dump_pickle
from pickle import load as load_pickle
from typing import Any
from uuid import UUID


def unsafe_object_to_bytes(data: Any) -> bytes:
    """用 pickle 把对象序列化成 bytes。**仅供完全可信的内部字节流**，喂外部输入等于 RCE。"""
    buf = BytesIO()
    dump_pickle(data, buf)
    buf.seek(0)
    return buf.getvalue()


def unsafe_bytes_to_object(data: bytes) -> Any:
    """用 pickle 把 bytes 反序列化成对象。**仅供完全可信的内部字节流**，喂外部输入等于 RCE。"""
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
    if isinstance(data, bool):
        return data
    if isinstance(data, (str, int, float)):
        return data
    # datetime 必须排在 date 前面，因为 datetime 是 date 的子类
    if isinstance(data, (datetime, date, time)):
        return data.isoformat()
    if isinstance(data, Decimal):
        return str(data)
    if isinstance(data, UUID):
        return str(data)
    if isinstance(data, PurePath):
        return str(data)
    if isinstance(data, (bytes, bytearray)):
        return b64encode(bytes(data)).decode("ascii")
    # 先处理namedtuple
    if callable(getattr(data, "_asdict", None)):
        return to_json_object(data._asdict())
    if isinstance(data, (list, tuple, set, frozenset)):
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
