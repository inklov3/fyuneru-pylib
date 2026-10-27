# fyuneru.gemini_toolkit

Google Gemini client 初始化、视频输入构造、错误分类与结构化 JSON 输出配置。

需要：`fyuneru[gemini]`

## 核心 API

### 初始化

```python
from fyuneru.gemini_toolkit import init_client, init_client_from_config

init_client(api_key: str, endpoint: str, api_version: str = "v1beta") -> Callable[[], Client]
# 创建 google.genai.Client，带自定义 endpoint + 认证 header。

init_client_from_config(config: dict) -> Callable[[], Client]
# 读 config["llm"]。当前只支持 provider="gemini"。
# 缺 "llm" 抛 KeyError；不支持的 provider 抛 ValueError。
```

### 视频输入

```python
from pathlib import Path
from fyuneru.gemini_toolkit import (
    VideoSource,
    bind_video_captioner,
    response_to_json_object,
    response_to_raw_dict,
)
from fyuneru.result import unwrap

# 预签名 URL（推荐）：请求体只有字符串，支持大文件
source = VideoSource(uri="https://s3.example.com/video.mp4?X-Amz-...")

# 本地路径：流式读取，不一次性加载整个文件
source = VideoSource(path=Path("local.mp4"), mime_type="video/mp4")

# 字节（仅适合小文件）
source = VideoSource(data=video_bytes)

# 绑定 captioner
captioner = bind_video_captioner(
    client,
    model="gemini-2.0-flash",
    content_config=build_content_config(schema=MyModel.model_json_schema()),
)

# 发起请求
result = captioner(prompt, source)
if is_failure(result):
    # 失败已分类为 GeminiTransientError / GeminiPermanentError
    raise result.error
response = unwrap(result)

# 解析响应
prompt_result = response_to_json_object(response)  # dict
raw_dict = response_to_raw_dict(response)          # 含 usage/finishReason/safety
```

### 错误分类

```python
from fyuneru.gemini_toolkit import (
    GeminiPermanentError,
    GeminiTransientError,
    classify_gemini_error,
)

try:
    response = client.models.generate_content(...)
except Exception as error:
    classified = classify_gemini_error(error)
    if isinstance(classified, GeminiTransientError):
        # 可重试：429, 5xx
        retry()
    elif isinstance(classified, GeminiPermanentError):
        # 永久失败：400, 403, 404, 模型名错误等
        log_and_fail()
    else:
        # 非 API 错误
        raise
```

### 结构化输出

```python
from fyuneru.gemini_toolkit import build_content_config

build_content_config(
    schema: dict[str, Any],
    response_mime_type: str = "application/json",
    temperature: float = 0,
    system_instruction: str | None = None,
) -> GenerateContentConfig
# 构建 Gemini 结构化 JSON 输出配置。
```

## VideoSource

```python
@dataclass(frozen=True)
class VideoSource:
    uri: str | None = None
    path: Path | None = None
    data: bytes | None = None
    mime_type: str = "video/mp4"
```

三种方式互斥，必须且只能提供一个：

- `uri`：走 fileData，由模型侧自行拉取，请求体只有字符串，是大文件的唯一可扩展路径（前提是该 URI 对模型服务可达）；
- `path`：走 inlineData，流式读取本地文件，不一次性加载到内存；
- `data`：走 inlineData，直接传字节，只适合小文件。

## bind_video_captioner

```python
def bind_video_captioner(
    client: Client,
    model: str,
    content_config: GenerateContentConfig | None = None,
) -> VideoCaptioner:
```

返回绑定了 client + model 的单次视频请求闭包。失败一律先过 `classify_gemini_error`，`Failure` 里装的已经是 Transient / Permanent 分类后的异常。

## 错误分类

### classify_gemini_error

```python
def classify_gemini_error(error: Exception) -> Exception:
```

把 google-genai 异常映射为瞬时 / 永久两类：

- `ServerError` → `GeminiTransientError`；
- `ClientError` / `APIError`：
  - 408, 429, 500, 502, 503, 504 → `GeminiTransientError`；
  - 其余 → `GeminiPermanentError`；
- 非 API 错误原样返回。

### GeminiTransientError

可重试的 Gemini 失败（限流、网关抖动）。

### GeminiPermanentError

确定不该重试的 Gemini 失败（请求非法、模型名错误等）。

## 响应解析

### response_to_json_object

```python
def response_to_json_object(response: GenerateContentResponse) -> dict[str, Any]:
```

取出响应文本并解析为 JSON 对象。只接受对象映射：契约字段都挂在顶层对象上，顶层是数组或标量说明模型没有遵守 schema。

### response_to_raw_dict

```python
def response_to_raw_dict(response: GenerateContentResponse) -> dict[str, Any]:
```

把完整响应转为可持久化 dict，用于归档原始回复。归档原始响应而不只是解析结果，是为了让 usage、finishReason、safety 这些只存在于原始体里的信息事后仍可追溯。

## 典型场景

### 1. 预签名 URL + 有界重试

```python
from fyuneru.gemini_toolkit import (
    GeminiTransientError,
    VideoSource,
    bind_video_captioner,
    response_to_json_object,
)
from fyuneru.retry import RetryPolicy, retry_call
from fyuneru.result import unwrap

captioner = bind_video_captioner(client, "gemini-2.0-flash", content_config)
source = VideoSource(uri=presigned_url)

response = retry_call(
    operation=lambda: unwrap(captioner(prompt, source)),
    policy=RetryPolicy(attempts=5, base_seconds=2.0),
    retry_on=(GeminiTransientError,),
    label="gemini_caption",
)

prompt_result = response_to_json_object(response)
```

### 2. 本地文件流式上传

```python
from pathlib import Path
from fyuneru.gemini_toolkit import VideoSource, bind_video_captioner

captioner = bind_video_captioner(client, "gemini-2.0-flash")
source = VideoSource(path=Path("local.mp4"))
result = captioner("describe this video", source)
```

### 3. 归档原始响应与结构化结果

```python
from io import BytesIO
import json
from fyuneru.gemini_toolkit import response_to_json_object, response_to_raw_dict
from fyuneru.s3_toolkit import bind_s3_writer

writer = bind_s3_writer(client, "workspace-bucket")
response = unwrap(captioner(prompt, source))

# 先保存原始响应
raw_dict = response_to_raw_dict(response)
writer("raw/unit-123.json", BytesIO(json.dumps(raw_dict).encode()))

# 再保存结构化结果
prompt_result = response_to_json_object(response)
validate_prompt_result(prompt_result, duration_seconds)
writer("result/unit-123.json", BytesIO(json.dumps(prompt_result).encode()))
```

## 关键约束

- `bind_video_captioner` 返回的闭包会自动分类异常，调用方据此决定重试策略；
- `VideoSource` 三种输入方式互斥，只能给一个；
- 预签名 URL 是大文件的唯一可扩展路径，前提是模型服务可访问该 URL；
- `response_to_json_object` 只接受顶层对象映射，顶层是数组或标量会立即失败；
- 默认 temperature=0、JSON mime；非 JSON 输出请显式改 `response_mime_type`；
- 只覆盖 Gemini 一家 provider，多 provider 抽象不在本库范围。
