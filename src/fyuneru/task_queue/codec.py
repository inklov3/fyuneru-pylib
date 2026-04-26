from __future__ import annotations

import json
from typing import Any

from fyuneru.converter import to_json_object


def normalize_payload(payload: Any) -> dict[str, Any]:
    normalized = to_json_object(payload)
    if not isinstance(normalized, dict):
        raise TypeError("payload 必须可序列化为对象映射")
    return normalized


def encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def decode_payload(raw_payload: str) -> dict[str, Any]:
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象映射")
    return payload
