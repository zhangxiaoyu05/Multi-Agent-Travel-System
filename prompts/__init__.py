"""Prompt 模板加载工具

使用方式：
    from prompts import load_prompt

    system_prompt = load_prompt("intent_router.txt")
"""

import os

_PROMPT_DIR = os.path.dirname(__file__)


def load_prompt(name: str) -> str:
    """加载 prompts/ 目录下的 .txt 模板文件

    Args:
        name: 模板文件名（如 "intent_router.txt"）

    Returns:
        去除首尾空白后的模板内容
    """
    path = os.path.join(_PROMPT_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()
