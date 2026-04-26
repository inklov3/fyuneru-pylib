from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from fyuneru.converter import to_json_object


def payload_type_name(payload_type: type[Any]) -> str:
    return f"{payload_type.__module__}.{payload_type.__qualname__}"


def normalize_payload_envelope(
    payload: Any,
    payload_type: type[Any] | None,
) -> dict[str, Any]:
    if payload_type is None:
        normalized = to_json_object(payload)
        if not isinstance(normalized, dict):
            raise TypeError("payload 必须可序列化为对象映射")
        return {
            "payload_type": "dict",
            "payload": normalized,
        }

    if not is_dataclass(payload_type):
        raise TypeError("payload_type 必须是 dataclass")
    if not isinstance(payload, payload_type):
        raise TypeError("payload 类型必须与 payload_type 一致")

    normalized = to_json_object(asdict(payload))
    if not isinstance(normalized, dict):
        raise TypeError("payload 必须可序列化为对象映射")

    return {
        "payload_type": payload_type_name(payload_type),
        "payload": normalized,
    }


def encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def decode_payload(raw_payload: str) -> dict[str, Any]:
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象映射")
    if "payload_type" not in payload or "payload" not in payload:
        raise ValueError("payload envelope 缺少必要字段")

    payload_type = payload["payload_type"]
    payload_data = payload["payload"]
    if not isinstance(payload_type, str):
        raise ValueError("payload_type 必须是字符串")
    if not isinstance(payload_data, dict):
        raise ValueError("payload 必须是对象映射")
    return payload


def decode_for_handler_payload(
    payload_envelope: dict[str, Any],
    payload_type: type[Any] | None,
) -> Any:
    envelope_type = payload_envelope["payload_type"]
    payload_data = payload_envelope["payload"]

    if not isinstance(envelope_type, str):
        raise ValueError("payload_type 必须是字符串")
    if not isinstance(payload_data, dict):
        raise ValueError("payload 必须是对象映射")

    if payload_type is None:
        if envelope_type != "dict":
            raise ValueError(f"未注册 payload_type: {envelope_type}")
        return payload_data

    expected_type = payload_type_name(payload_type)
    if envelope_type != expected_type:
        raise ValueError(
            f"payload_type 不匹配: expect {expected_type}, got {envelope_type}"
        )

    try:
        return payload_type(**payload_data)
    except TypeError as error:
        raise ValueError("payload 字段与 dataclass 不匹配") from error
