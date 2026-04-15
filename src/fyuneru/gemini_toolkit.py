from collections.abc import Callable
from functools import partial
from typing import Any

from google.genai import Client
from google.genai.types import GenerateContentConfig, HttpOptions


def init_client(
    api_key: str, endpoint: str, api_version: str = "v1beta"
) -> Callable[[], Client]:
    """初始化 Gemini 客户端

    Args:
        api_key: Gemini API 密钥
        endpoint: 自定义后端地址

    Returns:
        Callable[[], Client] 惰性初始化器
    """
    return partial(
        Client,
        api_key=api_key,
        http_options=HttpOptions(
            api_version=api_version,
            base_url=endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
        ),
    )


def build_content_config(
    schema: dict[str, Any],
    response_mime_type: str = "application/json",
    temperature: float = 0,
    system_instruction: str | None = None,
) -> GenerateContentConfig:
    return GenerateContentConfig(
        response_mime_type=response_mime_type,
        response_json_schema=schema,
        temperature=temperature,
        system_instruction=system_instruction,
    )
