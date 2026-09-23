"""测试 gemini_toolkit 的视频输入构造与错误分类。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from google.genai.errors import ClientError, ServerError

from fyuneru.gemini_toolkit import (
    DEFAULT_VIDEO_MIME_TYPE,
    GeminiPermanentError,
    GeminiTransientError,
    VideoSource,
    bind_video_captioner,
    build_video_contents,
    build_video_part,
    classify_gemini_error,
    response_to_json_object,
)
from fyuneru.result import Failure, is_failure, is_success, unwrap


class FakeResponse:
    def __init__(self, text: str | None):
        self.text = text

    def model_dump(self, mode: str, exclude_none: bool) -> dict:
        return {"text": self.text, "mode": mode, "exclude_none": exclude_none}


class FakeModels:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def generate_content(self, model, contents, config):
        self.calls.append(
            {"model": model, "contents": contents, "config": config}
        )
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, models: FakeModels):
        self.models = models


def _api_error_args(code: int) -> tuple[int, dict]:
    """google-genai 的 APIError 签名是 (code, response_json, response)。"""
    return code, {"error": {"code": code, "message": "boom"}}


def test_video_source_requires_exactly_one_input() -> None:
    for kwargs in (
        {},
        {"uri": "https://example.com/a.mp4", "data": b"x"},
        {"path": Path("a.mp4"), "data": b"x"},
    ):
        try:
            VideoSource(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"期望 ValueError: {kwargs}")

    source = VideoSource(uri="https://example.com/a.mp4")
    assert source.mime_type == DEFAULT_VIDEO_MIME_TYPE


def test_uri_source_builds_file_data_part() -> None:
    part = build_video_part(
        VideoSource(uri="https://example.com/a.mp4?sig=x")
    )
    assert part.file_data is not None, "uri 必须走 fileData"
    assert part.file_data.file_uri == "https://example.com/a.mp4?sig=x"
    assert part.file_data.mime_type == "video/mp4"
    assert part.inline_data is None, "uri 不得把字节塞进请求体"


def test_path_source_builds_inline_part() -> None:
    with TemporaryDirectory() as tmp:
        video = Path(tmp) / "a.mp4"
        video.write_bytes(b"\x00\x01\x02")
        part = build_video_part(VideoSource(path=video))
    assert part.inline_data is not None, "path 必须走 inlineData"
    assert part.inline_data.data == b"\x00\x01\x02"


def test_empty_video_bytes_rejected() -> None:
    try:
        build_video_part(VideoSource(data=b""))
    except ValueError:
        return
    raise AssertionError("空视频内容必须被拒绝")


def test_contents_put_video_before_prompt() -> None:
    contents = build_video_contents(
        "describe", VideoSource(uri="https://example.com/a.mp4")
    )
    assert len(contents) == 1
    parts = contents[0].parts
    assert parts is not None and len(parts) == 2
    assert parts[0].file_data is not None, "视频必须排在第一位"
    assert parts[1].text == "describe"
    assert contents[0].role == "user"


def test_blank_prompt_rejected() -> None:
    try:
        build_video_contents(
            "   ", VideoSource(uri="https://example.com/a.mp4")
        )
    except ValueError:
        return
    raise AssertionError("空 prompt 必须被拒绝")


def test_error_classification() -> None:
    server = ServerError(*_api_error_args(503))
    assert isinstance(classify_gemini_error(server), GeminiTransientError)

    throttled = ClientError(*_api_error_args(429))
    assert isinstance(classify_gemini_error(throttled), GeminiTransientError)

    bad_request = ClientError(*_api_error_args(400))
    assert isinstance(classify_gemini_error(bad_request), GeminiPermanentError)

    unrelated = ValueError("local")
    assert classify_gemini_error(unrelated) is unrelated, "非 API 错误原样返回"


def test_captioner_success_and_failure() -> None:
    models = FakeModels(response=FakeResponse('{"a": 1}'))
    caption = bind_video_captioner(FakeClient(models), model="gemini-x")  # type: ignore[arg-type]
    result = caption("prompt", VideoSource(uri="https://example.com/a.mp4"))
    assert is_success(result)
    assert models.calls[0]["model"] == "gemini-x"

    failing = FakeModels(error=ClientError(*_api_error_args(400)))
    caption_bad = bind_video_captioner(FakeClient(failing), model="gemini-x")  # type: ignore[arg-type]
    bad = caption_bad("prompt", VideoSource(uri="https://example.com/a.mp4"))
    assert is_failure(bad)
    assert isinstance(bad, Failure)
    assert isinstance(bad.error, GeminiPermanentError), (
        f"400 应分类为永久失败，得到 {type(bad.error)}"
    )


def test_blank_model_rejected() -> None:
    try:
        bind_video_captioner(FakeClient(FakeModels()), model=" ")  # type: ignore[arg-type]
    except ValueError:
        return
    raise AssertionError("空 model 必须被拒绝")


def test_response_json_parsing() -> None:
    assert response_to_json_object(FakeResponse('{"a": 1}')) == {"a": 1}  # type: ignore[arg-type]

    for text in (None, "  ", "[1, 2]", "not-json"):
        try:
            response_to_json_object(FakeResponse(text))  # type: ignore[arg-type]
        except (ValueError, Exception):
            continue
        raise AssertionError(f"非法响应必须被拒绝: {text!r}")


def main() -> None:
    test_video_source_requires_exactly_one_input()
    test_uri_source_builds_file_data_part()
    test_path_source_builds_inline_part()
    test_empty_video_bytes_rejected()
    test_contents_put_video_before_prompt()
    test_blank_prompt_rejected()
    test_error_classification()
    test_captioner_success_and_failure()
    test_blank_model_rejected()
    test_response_json_parsing()
    print("test_gemini_toolkit: 全部通过")


if __name__ == "__main__":
    main()
