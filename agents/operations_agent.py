"""运营 Agent——商家入驻 + 订单履约 + 售后工单

使用 BaseAgent 内置的 _run_tool_calling_loop 处理标准 tool-calling 流程。
所有操作强制 CRM 记录。
"""

import json
from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_crm import update_crm
from tools.mock_capi import send_capi
from services.llm import get_agent_llm
from prompts import load_prompt


class OperationsAgent(BaseAgent):
    """运营 Agent——CRM + CAPI + 工单处理"""

    def __init__(self):
        llm = get_agent_llm()
        tools = [update_crm, send_capi]
        system_prompt = load_prompt("operations_agent.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    async def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        language = self._get_language(state)
        customer_id = state.get("customer_id", "unknown")

        if not user_msg:
            return {
                "final_reply": "您好！我是运营专员，有什么运营相关的问题需要处理吗？",
                "need_human": False,
            }

        # 标准 tool-calling 循环
        loop_result = await self._run_tool_calling_loop(user_msg, language=language)
        final_text = loop_result["final_text"]
        need_human = loop_result["need_human"]
        crm_result = loop_result["tool_results"].get("update_crm", "")

        # 升级关键词检测
        escalation_keywords = [
            "投诉", "退款", "骗人", "诈骗", "报警", "重大事故",
            "伤亡", "安全事故", "媒体曝光",
        ]
        for kw in escalation_keywords:
            if kw in user_msg:
                need_human = True
                break

        # 如果 LLM 未调用 CRM，强制补充一条记录
        if not crm_result:
            session_summary = json.dumps({
                "customer_id": customer_id,
                "branch": "operations",
                "user_message": user_msg[:200],
                "need_human": need_human,
            }, ensure_ascii=False)
            try:
                update_crm.invoke({
                    "customer_id": customer_id,
                    "session_data": session_summary,
                })
            except Exception:
                pass

        return {
            "final_reply": final_text,
            "need_human": need_human,
        }


_agent_instance: OperationsAgent | None = None


def get_operations_agent() -> OperationsAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = OperationsAgent()
    return _agent_instance
