# fyuneru.markdown_utils

去掉 Markdown 代码块包裹，保留正文。默认安装。

## API

```python
from fyuneru.markdown_utils import unwrap_codeblock

unwrap_codeblock(text: str) -> str
# 剥掉 markdown 代码围栏，保留内部内容。
# "```python\nprint('hello')\n```" -> "print('hello')\n"
```

典型用途：LLM 返回带 ``` 围栏的代码/JSON 时先剥壳再解析。
