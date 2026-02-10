"""数据转化器"""

from io import BytesIO
from pickle import dump as dump_pickle
from pickle import load as load_pickle


def object_to_bytes(data: any) -> bytes:
    buf = BytesIO()
    dump_pickle(data, buf)
    buf.seek(0)
    return buf.getvalue()


def bytes_to_object(data: bytes) -> any:
    buf = BytesIO(data)
    buf.seek(0)
    return load_pickle(buf)
