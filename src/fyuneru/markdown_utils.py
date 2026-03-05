from re import DOTALL, sub


def unwrap_codeblock(text: str) -> str:
    """
    清除 markdown 代码包裹格式, 保留代码块内容
    """
    return sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=DOTALL)
