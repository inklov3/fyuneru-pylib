# fyuneru.gemini_toolkit

Google Gemini client 初始化与结构化 JSON 输出配置。

需要：`fyuneru[gemini]`

## API

```python
from fyuneru.gemini_toolkit import init_client, init_client_from_config, build_content_config

init_client(api_key: str, endpoint: str, api_version: str = "v1beta") -> Callable[[], Client]
# 创建 google.genai.Client，带自定义 endpoint + 认证 header。

init_client_from_config(config: dict) -> Callable[[], Client]
# 读 config["llm"]。当前只支持 provider="gemini"。
# 缺 "llm" 抛 KeyError；不支持的 provider 抛 ValueError。

build_content_config(
    schema: dict[str, Any],
    response_mime_type: str = "application/json",
    temperature: float = 0,
    system_instruction: str | None = None,
) -> GenerateContentConfig
# 构建 Gemini 结构化 JSON 输出配置。
```

## 用法（结构化输出）

```python
from fyuneru.gemini_toolkit import init_client, build_content_config

client = init_client(api_key="sk_xxx", endpoint="https://xxx")()
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[prompt],
    config=build_content_config(
        schema=MyModel.model_json_schema(),
        system_instruction=system_prompt,
    ),
)
result = MyModel.model_validate_json(response.text)
```

## 关键约束

- 默认 temperature=0、JSON mime；非 JSON 输出请显式改 `response_mime_type`
- 只覆盖 Gemini 一家 provider，多 provider 抽象不在本库范围
