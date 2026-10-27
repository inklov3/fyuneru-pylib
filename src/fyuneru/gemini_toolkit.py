import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol, cast

from google.genai import Client
from google.genai.errors import APIError, ClientError, ServerError
from google.genai.types import (
    Content,
    ContentListUnionDict,
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    Part,
)

from fyuneru.result import ResultE, safe


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


def init_client_from_config(config: dict) -> Callable[[], Client]:
    """从配置构建 gemini client initializer。

    config["llm"] 必须包含 api_key, endpoint, provider (必须为 "gemini")。可选: api_version。
    """
    llm_cfg = config["llm"]
    provider = llm_cfg["provider"]
    if provider != "gemini":
        raise ValueError(f"不支持的 LLM provider: {provider}")
    return init_client(
        api_key=llm_cfg["api_key"],
        endpoint=llm_cfg["endpoint"],
        api_version=llm_cfg.get("api_version", "v1beta"),
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


# ----------------------------------------------------------------------
# 视频输入
# ----------------------------------------------------------------------

DEFAULT_VIDEO_MIME_TYPE = "video/mp4"

# 5xx 与 429 属于上游瞬时状态，重试有意义；其余 4xx 是请求本身的问题，
# 重试只会等量复现，所以在 classify 里被判为永久失败。
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class GeminiPermanentError(RuntimeError):
    """确定不该重试的 Gemini 失败（请求非法、模型名错误等）。"""


class GeminiTransientError(RuntimeError):
    """可重试的 Gemini 失败（限流、网关抖动）。"""


@dataclass(frozen=True)
class VideoSource:
    """一次视频输入的来源。三种方式互斥，必须恰好给一个。

    `uri` 走 fileData，由模型侧自行拉取，请求体里只有一个字符串，是大文件的
    唯一可扩展路径——前提是该 URI 对模型服务可达（预签名 URL 即为此而来）。
    `path` / `data` 走 inlineData，视频字节进请求体，只适合小文件。
    """

    uri: str | None = None
    path: Path | None = None
    data: bytes | None = None
    mime_type: str = DEFAULT_VIDEO_MIME_TYPE

    def __post_init__(self) -> None:
        provided = [
            name
            for name, value in (
                ("uri", self.uri),
                ("path", self.path),
                ("data", self.data),
            )
            if value is not None
        ]
        if len(provided) != 1:
            raise ValueError(
                "VideoSource 必须且只能提供 uri / path / data 之一，"
                f"当前: {provided or '无'}"
            )
        if not self.mime_type.strip():
            raise ValueError("mime_type 不能为空")


def build_video_part(source: VideoSource) -> Part:
    """把 `VideoSource` 转成 Gemini 的视频 Part。"""
    if source.uri is not None:
        return Part.from_uri(
            file_uri=source.uri,
            mime_type=source.mime_type,
        )
    payload = source.path.read_bytes() if source.path is not None else source.data
    if not payload:
        raise ValueError("视频内容为空")
    return Part.from_bytes(data=payload, mime_type=source.mime_type)


def build_video_contents(
    prompt: str,
    source: VideoSource,
) -> list[Content]:
    """构造 [视频, 提示词] 的单轮 user content。

    视频排在提示词之前：契约类提示词要引用"这段视频"，先给素材再给指令，
    模型就不必回指尚未出现的内容。
    """
    if not prompt.strip():
        raise ValueError("prompt 不能为空")
    return [
        Content(
            role="user",
            parts=[
                build_video_part(source),
                Part.from_text(text=prompt),
            ],
        )
    ]


def classify_gemini_error(error: Exception) -> Exception:
    """把 google-genai 异常映射为瞬时 / 永久两类。

    调用方据此决定是本地退避重试还是直接失败——把 400 当瞬时错误去重试，
    只会把一个确定的 bug 拖成一串超时。
    """
    if isinstance(error, ServerError):
        return GeminiTransientError(str(error))
    if isinstance(error, (ClientError, APIError)):
        code = getattr(error, "code", None)
        if isinstance(code, int) and code in RETRYABLE_STATUS_CODES:
            return GeminiTransientError(str(error))
        return GeminiPermanentError(str(error))
    return error


class VideoCaptioner(Protocol):
    def __call__(
        self,
        prompt: str,
        source: VideoSource,
    ) -> ResultE[GenerateContentResponse]: ...


def bind_video_captioner(
    client: Client,
    model: str,
    content_config: GenerateContentConfig | None = None,
) -> VideoCaptioner:
    """绑定 client + model，返回单次视频请求闭包。

    失败一律先过 `classify_gemini_error`，所以 `Failure` 里装的已经是
    Transient / Permanent 分类后的异常。
    """
    if not model.strip():
        raise ValueError("model 不能为空")

    @safe
    def caption(
        prompt: str,
        source: VideoSource,
    ) -> GenerateContentResponse:
        try:
            return client.models.generate_content(
                model=model,
                # google-genai 的 contents 联合类型把 dataclass 形式与 TypedDict
                # 形式排列在一起，list[Content] 在运行时完全合法但静态上不可
                # 赋值，此处只做类型断言，不改变传入值。
                contents=cast(
                    ContentListUnionDict,
                    build_video_contents(prompt, source),
                ),
                config=content_config,
            )
        except Exception as error:
            raise classify_gemini_error(error) from error

    return caption


def response_to_json_object(
    response: GenerateContentResponse,
) -> dict[str, Any]:
    """取出响应文本并解析为 JSON 对象。

    只接受对象映射：契约字段都挂在顶层对象上，顶层是数组或标量说明模型没有
    遵守 schema，此时早失败比让下游取字段时崩掉更好定位。
    """
    text = response.text
    if text is None or not text.strip():
        raise ValueError("Gemini 响应不含文本内容")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini 响应 JSON 顶层必须是对象映射")
    return parsed


def response_to_raw_dict(
    response: GenerateContentResponse,
) -> dict[str, Any]:
    """把完整响应转为可持久化 dict，用于归档原始回复。

    归档原始响应而不只是解析结果，是为了让 usage、finishReason、safety
    这些只存在于原始体里的信息事后仍可追溯。
    """
    return response.model_dump(mode="json", exclude_none=True)
