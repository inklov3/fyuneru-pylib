# fyuneru

> molar 工作库

## 快捷模块及用法

### gemini_client.py

``` python
from fyuneru.gemini_client import init_client as init_gemini_client
from fyuneru.gemini_client import get_config as get_model_config
# 创建客户端
gemini_getter: Callable[[], Client] = init_gemini_client(
    api_key="sk_xxxx",
    endpoint="http(s)://xxx"
)

client = gemini_getter()

response = client.models.generate_content(
    model="geminixxx",
    contents=[userprompt, image],
    config=get_model_config(
        schema=BaseModel.model_json_schema(),
        system_instruction=system_prompt,
    )
    result: BaseModel = BaseModel.model_validate_json(response.text)
)
```