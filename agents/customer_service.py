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

        # 使用基类标准 tool-calling 循环
        loop_result = await self._run_tool_calling_loop(user_msg, language=language)

        return {
            "final_reply": loop_result["final_text"],
            "need_human": loop_result["need_human"],
        }


# 模块级单例
_agent_instance: CustomerServiceAgent | None = None


def get_customer_service_agent() -> CustomerServiceAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CustomerServiceAgent()
    return _agent_instance
