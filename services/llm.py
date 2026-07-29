"""LLM 工厂——阿里百炼平台

统一管理 LLM 实例创建，通过环境变量切换 provider/model。
使用模块级单例避免重复实例化。

使用方式：
    from services.llm import get_router_llm, get_agent_llm

    router_llm = get_router_llm()   # 轻量模型，用于意图路由
    agent_llm = get_agent_llm()     # 强模型，用于内容生成
"""

import os
from langchain_openai import ChatOpenAI

# 百炼兼容 OpenAI SDK 的 base_url
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# =============================================================================
# 模块级单例缓存
# =============================================================================

_router_llm: ChatOpenAI | None = None
_agent_llm: ChatOpenAI | None = None


def get_router_llm() -> ChatOpenAI:
    """意图路由器用轻量模型（qwen-turbo：快速、低成本）

    环境变量：
        ROUTER_MODEL: 模型名（默认 qwen-turbo）
        LLM_API_KEY: 百炼 API Key
        LLM_BASE_URL: base_url（默认百炼地址）
        ROUTER_TEMPERATURE: 温度（默认 0.3）
        ROUTER_MAX_TOKENS: 最大输出 token（默认 512）
    """
    global _router_llm
    if _router_llm is None:
        _router_llm = ChatOpenAI(
            model=os.getenv("ROUTER_MODEL", "qwen-turbo"),
            api_key=os.getenv("LLM_API_KEY", "sk-placeholder"),
            base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
            temperature=float(os.getenv("ROUTER_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("ROUTER_MAX_TOKENS", "512")),
        )
    return _router_llm


def get_agent_llm() -> ChatOpenAI:
    """Agent 内容生成用强模型（qwen-plus：长文本、强推理）

    环境变量：
        AGENT_MODEL: 模型名（默认 qwen-plus）
        LLM_API_KEY: 百炼 API Key
        LLM_BASE_URL: base_url（默认百炼地址）
        AGENT_TEMPERATURE: 温度（默认 0.7）
        AGENT_MAX_TOKENS: 最大输出 token（默认 4096）
    """
    global _agent_llm
    if _agent_llm is None:
        _agent_llm = ChatOpenAI(
            model=os.getenv("AGENT_MODEL", "qwen-plus"),
            api_key=os.getenv("LLM_API_KEY", "sk-placeholder"),
            base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("AGENT_MAX_TOKENS", "4096")),
        )
    return _agent_llm
