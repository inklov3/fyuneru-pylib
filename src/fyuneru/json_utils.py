from re import DOTALL, sub


def unwarp_markdown(text: str) -> str:
    """
    清除 markdown 中的代码块, 保留内容
    """
    return sub(r"```[^\n]*\n(.*?)```", "", text, flags=DOTALL)
