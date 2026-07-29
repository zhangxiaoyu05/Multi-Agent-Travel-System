"""入参保护节点

在消息进入图之前做安全检查：
- 截断过长消息（保护 LLM 上下文窗口）
- 基础 PII 脱敏（手机号等）
"""

import re
from graph.state import AgentState


# 手机号正则（中国大陆）
_PHONE_RE = re.compile(r'\b1[3-9]\d{9}\b')


def input_guard(state: AgentState) -> dict:
    """入参保护：消息长度截断 + 基础清洗

    Args:
        state: 当前 AgentState

    Returns:
        要合并到 State 的字段 dict（此处只更新 messages）
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_msg = messages[-1]
    content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    # 长度截断（保护 LLM 上下文窗口）
    max_length = 4000
    if len(content) > max_length:
        content = content[:max_length] + "..."

    # 简单 PII 脱敏：中国大陆手机号
    content = _PHONE_RE.sub("[PHONE]", content)

    # 更新最后一条消息的内容
    last_msg.content = content

    return {"messages": messages}
