"""Prompt 模板加载工具（支持多语言）

使用方式：
    from prompts import load_prompt, get_language_instruction

    system_prompt = load_prompt("intent_router.txt")
    lang_instr = get_language_instruction("ja")
"""

import os

_PROMPT_DIR = os.path.dirname(__file__)

# 语言指令映射——注入到 system prompt 中驱动 LLM 以目标语言回复
_LANG_INSTRUCTIONS = {
    "zh": "",  # 中文是默认训练语言，无需额外指令
    "en": "\n\n[Language] You MUST respond in English only. All replies must be in English.",
    "ja": "\n\n[Language] 必ず日本語のみで回答してください。すべての返信は日本語で行ってください。",
    "ko": "\n\n[Language] 반드시 한국어로만 응답하세요. 모든 답변은 한국어로 작성해야 합니다.",
}


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


def get_language_instruction(language: str) -> str:
    """返回注入到 system prompt 的语言指令

    Args:
        language: 语言代码（zh/en/ja/ko）

    Returns:
        语言指令字符串；zh 返回空字符串（中文是默认行为）
    """
    return _LANG_INSTRUCTIONS.get(language, "")
