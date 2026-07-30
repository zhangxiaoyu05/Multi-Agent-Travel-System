"""客服 Agent——FAQ 答疑 + 转人工判断

负责处理客服类用户消息：
1. 调用 search_faq 工具检索 FAQ 知识库
2. 调用 check_handoff 工具评估是否需要转人工
3. 基于工具返回信息生成友好回复
"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.rag_faq import search_faq   # Phase 7：RAG 向量检索 + 关键词兜底
from tools.mock_handoff import check_handoff
from services.llm import get_agent_llm
from prompts import load_prompt


class CustomerServiceAgent(BaseAgent):
    """客服 Agent

    使用 LLM + Tools 模式处理客服咨询。
    """

    def __init__(self):
        llm = get_agent_llm()
        tools = [search_faq, check_handoff]
        system_prompt = load_prompt("customer_service.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    def run(self, state: AgentState) -> dict:
        """处理客服咨询

        流程：
        1. 提取用户消息
        2. LLM 决策：直接回复 or 调用工具
        3. 如果调用了工具，将结果回传给 LLM 生成最终回复

        Args:
            state: 当前 AgentState

        Returns:
            dict 包含 final_reply 和 need_human
        """
        user_msg = self._get_user_message(state)

        if not user_msg:
            return {
                "final_reply": "您好，请问有什么可以帮您的？",
                "need_human": False,
            }

        # Step 1: LLM 决策 —— 调用工具或直接回复
        llm_with_tools = self.llm.bind_tools(self.tools)

        response = llm_with_tools.invoke([
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ])

        # Step 2: 处理工具调用
        need_human = False
        faq_result = ""
        handoff_result = ""

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                if tool_name == "search_faq":
                    faq_result = search_faq.invoke(tool_args)
                elif tool_name == "check_handoff":
                    handoff_result = check_handoff.invoke(tool_args)
                    if "需要转人工" in str(handoff_result):
                        need_human = True

        # Step 3: 如果有工具调用，把结果回传给 LLM 生成最终回复
        if response.tool_calls:
            # 构建工具结果消息
            tool_messages = []
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                if tool_name == "search_faq" and faq_result:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": faq_result,
                    })
                elif tool_name == "check_handoff" and handoff_result:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": handoff_result,
                    })

            if tool_messages:
                # 构建对话消息链
                conversation = [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_msg},
                    response,  # AIMessage with tool_calls
                ] + tool_messages

                final_response = self.llm.invoke(conversation)
                return {
                    "final_reply": final_response.content,
                    "need_human": need_human,
                }

        # 没有工具调用：LLM 直接回复
        return {
            "final_reply": response.content,
            "need_human": need_human,
        }


# 模块级单例（Agent 无状态，可复用）
_agent_instance: CustomerServiceAgent | None = None


def get_customer_service_agent() -> CustomerServiceAgent:
    """获取客服 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CustomerServiceAgent()
    return _agent_instance
