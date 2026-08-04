"""查询改写节点

在意图路由之前对用户原始输入做一层纠错改写：
- 拼音 → 中文（如 "bei jing" → "北京"）
- 中英混杂 → 统一中文
- 错别字修正
- 省略语义补充

这能显著提升后续意图路由、RAG 检索、字段提取的准确率。
"""

import re
import logging
from graph.state import AgentState
from services.llm import get_light_llm
from prompts import load_prompt

logger = logging.getLogger(__name__)

# 跳过改写的短确认消息（这些不需要改写，改写反而可能引入错误）
_SKIP_PATTERNS = [
    r"^[好的嗯行对可以OKokYesyesNo]+[!！。.]*$",
    r"^[是的对]+[!！。.]*$",
    r"^(thanks?|thank you|谢谢|感谢|多谢)[!！。.]*$",
    r"^[知道了明白懂了了解][!！了。.]*$",
    r"^[继续下一步][!！。.]*$",
]

# 最短改写长度（字符数，太短的消息不需要改写）
_MIN_LENGTH_FOR_REWRITE = 3


def _should_skip(text: str) -> bool:
    """判断是否跳过改写"""
    stripped = text.strip()
    if len(stripped) < _MIN_LENGTH_FOR_REWRITE:
        return True
    for pattern in _SKIP_PATTERNS:
        if re.search(pattern, stripped):
            return True
    return False


def _has_rewrite_need(text: str) -> bool:
    """快速判断是否有改写必要（避免不必要的 LLM 调用）

    检查是否存在以下情况：
    - 拼音（连续的小写英文字母 + 空格 + 数字的混合模式）
    - 中英混杂
    - 明显的拼写错误标记
    """
    # 包含英文单词（可能是拼音或混杂）
    has_english = bool(re.search(r"[a-zA-Z]{2,}", text))
    # 包含数字与中文混杂（如 "3days", "2person"）
    has_mixed_alnum = bool(re.search(r"\d+[a-zA-Z]+|[a-zA-Z]+\d+", text))
    # 包含明显的拼音模式（小写字母 + 空格 + 数字/中文，如 "bei jing 3天"）
    has_pinyin_pattern = bool(re.search(r"[a-zA-Z]+\s+[a-zA-Z]+", text))
    # 中文 + 英文单词混排（如 "我想去beijing"）
    has_cn_en_mix = bool(re.search(r"[一-鿿][a-zA-Z]{2,}|[a-zA-Z]{2,}[一-鿿]", text))

    return has_english or has_mixed_alnum or has_pinyin_pattern or has_cn_en_mix


def query_rewrite(state: AgentState) -> dict:
    """查询改写节点——将用户原始输入规范化为清晰中文

    流程：
    1. 提取最后一条用户消息
    2. 快速判断是否需要改写（跳过短确认、已规范文本）
    3. 调用 LLM 改写
    4. 替换消息内容 + 保存原始文本

    Args:
        state: 当前 AgentState

    Returns:
        要合并到 State 的字段 dict
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_msg = messages[-1]
    # 只处理用户消息
    if hasattr(last_msg, "type") and last_msg.type != "human":
        return {}

    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    if not user_text or not user_text.strip():
        return {}

    original = user_text.strip()

    # 快速跳过：无需改写的短消息
    if _should_skip(original):
        logger.debug("Query rewrite skipped (short/confirmation): %s", original[:50])
        return {"original_query": original}

    # 快速判断：是否需要改写
    if not _has_rewrite_need(original):
        logger.debug("Query rewrite skipped (already clean): %s", original[:50])
        return {"original_query": original}

    # 调用 LLM 改写
    try:
        system_prompt = load_prompt("query_rewrite.txt")
        llm = get_light_llm()
        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": original},
        ])
        rewritten = response.content.strip()

        # 防御：如果 LLM 返回空或太短，保留原文
        if not rewritten or len(rewritten) < 2:
            logger.warning("Query rewrite returned empty/short result, keeping original")
            return {"original_query": original}

        # 防御：如果改写结果与原文完全相同，无需更新
        if rewritten == original:
            return {"original_query": original}

        logger.info("Query rewritten: %r → %r", original[:80], rewritten[:80])

        # 替换最后一条消息的内容
        last_msg.content = rewritten

        return {
            "messages": messages,
            "original_query": original,
        }

    except Exception as e:
        logger.warning("Query rewrite LLM call failed: %s, keeping original", e)
        return {"original_query": original}
