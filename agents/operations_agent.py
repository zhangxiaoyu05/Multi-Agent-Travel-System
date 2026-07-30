"""运营 Agent——商家入驻 + 订单履约 + 售后工单

OperationsAgent 负责处理运营类用户消息：
1. 商家入驻流程引导
2. 订单履约跟踪与协调
3. 售后工单处理（改期/退订/投诉）
4. 平台规则咨询
5. 所有操作写入 CRM + 发送 CAPI 事件
"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_crm import update_crm
from tools.mock_capi import send_capi
from services.llm import get_agent_llm
from prompts import load_prompt

import json


class OperationsAgent(BaseAgent):
    """运营 Agent

    使用 LLM + Tools 模式处理运营任务。
    tools 中包含 update_crm 和 send_capi。
    所有操作必须记录到 CRM。
    """

    def __init__(self):
        llm = get_agent_llm()
        tools = [update_crm, send_capi]
        system_prompt = load_prompt("operations_agent.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    def run(self, state: AgentState) -> dict:
        """处理运营任务

        流程：
        1. 提取用户消息和会话上下文
        2. LLM 分析运营诉求
        3. 根据需要调用 update_crm / send_capi
        4. 生成可执行的回复

        Args:
            state: 当前 AgentState

        Returns:
            dict 包含 final_reply, need_human, crm_written
        """
        user_msg = self._get_user_message(state)
        customer_id = state.get("customer_id", "unknown")

        if not user_msg:
            return {
                "final_reply": "您好！我是运营专员，有什么运营相关的问题需要处理吗？",
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
        crm_result = ""
        capi_result = ""

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                if tool_name == "update_crm":
                    crm_result = update_crm.invoke(tool_args)
                elif tool_name == "send_capi":
                    capi_result = send_capi.invoke(tool_args)

        # Step 3: 如果调用了工具，把结果回传给 LLM 生成最终回复
        if response.tool_calls:
            tool_messages = []
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                if tool_name == "update_crm" and crm_result:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": crm_result,
                    })
                elif tool_name == "send_capi" and capi_result:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": capi_result,
                    })

            if tool_messages:
                conversation = [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_msg},
                    response,
                ] + tool_messages

                final_response = self.llm.invoke(conversation)
                final_text = final_response.content
            else:
                final_text = response.content
        else:
            final_text = response.content

        # Step 4: 检测严重投诉/需要转人工
        escalation_keywords = [
            "投诉", "退款", "骗人", "诈骗", "报警", "重大事故",
            "伤亡", "安全事故", "媒体曝光",
        ]
        for kw in escalation_keywords:
            if kw in user_msg:
                need_human = True
                break

        # Step 5: 如果 LLM 没有调用 CRM，强制补充一条 CRM 记录
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
                pass  # Mock 阶段忽略

        return {
            "final_reply": final_text,
            "need_human": need_human,
        }


# 模块级单例
_agent_instance: OperationsAgent | None = None


def get_operations_agent() -> OperationsAgent:
    """获取运营 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = OperationsAgent()
    return _agent_instance
