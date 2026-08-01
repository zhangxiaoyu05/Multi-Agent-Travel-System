"""客服 Agent——FAQ 答疑 + 转人工判断

使用 BaseAgent 内置的 _run_tool_calling_loop 处理标准 tool-calling 流程。
"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.rag_faq import search_faq
from tools.mock_handoff import check_handoff
from services.llm import get_agent_llm
from prompts import load_prompt


class CustomerServiceAgent(BaseAgent):
    """客服 Agent——FAQ 检索 + 转人工评估"""

    def __init__(self):
        llm = get_agent_llm()
        tools = [search_faq, check_handoff]
        system_prompt = load_prompt("customer_service.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    async def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        language = self._get_language(state)

        if not user_msg:
            return {
                "final_reply": "您好，请问有什么可以帮您的？",
                "need_human": False,
            }

        # 🧠 构建用户画像上下文
        extra_context = self._build_context(state)

        # 使用基类标准 tool-calling 循环
        loop_result = await self._run_tool_calling_loop(
            user_msg, language=language, extra_context=extra_context,
        )

        return {
            "final_reply": loop_result["final_text"],
            "need_human": loop_result["need_human"],
        }

    @staticmethod
    def _build_context(state: AgentState) -> dict:
        """从 State 中的画像/偏好构建附加上下文"""
        ctx = {}
        profile = state.get("user_profile", {}) or {}
        prefs = state.get("user_preferences", {}) or {}

        if profile.get("nationality"):
            ctx["客户国籍"] = profile["nationality"]
        if profile.get("preferred_language"):
            ctx["语言偏好"] = profile["preferred_language"]
        if profile.get("preferred_destinations"):
            dests = profile["preferred_destinations"]
            if isinstance(dests, list):
                ctx["意向目的地"] = ", ".join(dests)
            else:
                ctx["意向目的地"] = str(dests)
        if profile.get("travel_style"):
            ctx["节奏偏好"] = profile["travel_style"]
        if profile.get("interests"):
            interests = profile["interests"]
            if isinstance(interests, list):
                ctx["兴趣"] = ", ".join(interests)
            else:
                ctx["兴趣"] = str(interests)
        if profile.get("travel_companion"):
            ctx["同行人"] = profile["travel_companion"]
        if profile.get("special_needs"):
            needs = profile["special_needs"]
            if isinstance(needs, list):
                ctx["特殊需求"] = ", ".join(needs)
            else:
                ctx["特殊需求"] = str(needs)

        return ctx


# 模块级单例
_agent_instance: CustomerServiceAgent | None = None


def get_customer_service_agent() -> CustomerServiceAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CustomerServiceAgent()
    return _agent_instance
