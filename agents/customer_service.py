"""客服 Agent——FAQ 知识库检索 + 转人工判断

检索流程（双路 + RRF 融合）：
    1. 用户问题 → search_faq（向量 + BM25 → RRF → Top-K）
    2. 检索结果注入提示词模板
    3. LLM 基于知识库内容 + 原始问题生成回答
    4. 若检索无结果且包含投诉/退款关键词 → check_handoff 转人工
"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.rag_faq import search_faq
from tools.mock_handoff import check_handoff
from services.llm import get_agent_llm
from services.stream_bridge import push_token
from prompts import load_prompt, get_language_instruction


class CustomerServiceAgent(BaseAgent):
    """客服 Agent——RAG 检索 + 转人工评估"""

    def __init__(self):
        llm = get_agent_llm()
        # 仅注册 check_handoff 作为 LLM 可选工具（search_faq 由 Agent 主动调用）
        tools = [check_handoff]
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

        # =====================================================================
        # Step 1: 主动执行知识库检索（非 LLM 决策，必须执行）
        # =====================================================================
        rag_context = ""
        try:
            rag_raw = search_faq.invoke({"query": user_msg})
            if rag_raw and "参考资料" in rag_raw:
                rag_context = rag_raw
        except Exception:
            rag_context = ""

        # =====================================================================
        # Step 2: 构建提示词（检索结果 + 用户画像 + 原始问题）
        # =====================================================================
        profile_context = self._build_context(state)
        lang_instr = get_language_instruction(language)

        # 组装 system prompt
        system_content = self.system_prompt + lang_instr

        # 注入检索上下文
        if rag_context:
            system_content = system_content.replace(
                "{{RAG_CONTEXT}}",
                f"\n\n## 知识库检索结果（基于用户问题的实时检索）\n\n{rag_context}",
            )
        else:
            system_content = system_content.replace(
                "{{RAG_CONTEXT}}",
                "\n\n## 知识库检索结果\n\n（本次检索未找到相关知识库内容，请基于自身知识谨慎回答，不要编造。）",
            )

        # 注入用户画像
        if profile_context:
            ctx_str = "\n".join(f"- {k}: {v}" for k, v in profile_context.items())
            system_content += f"\n\n## 当前用户画像\n\n{ctx_str}"

        # 注入原始用户问题（让 LLM 明确知道要回答什么）
        system_content += (
            f"\n\n## 用户原始问题\n\n{user_msg}"
            f"\n\n请基于以上知识库检索结果和用户画像，回答用户的问题。"
            f"如果知识库内容足以回答问题，请直接引用；如果不够，请诚实说明并提供替代建议。"
        )

        # =====================================================================
        # Step 3: LLM 生成回答（check_handoff 仍作为可选工具）
        # =====================================================================
        llm_with_tools = self.llm.bind_tools(self.tools)
        response = await llm_with_tools.ainvoke([
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_msg},
        ])

        need_human = False
        final_text = response.content

        # 处理 check_handoff 工具调用
        if response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] == "check_handoff":
                    tool_result = self._execute_tool("check_handoff", tc.get("args", {}))
                    if "需要转人工" in str(tool_result):
                        need_human = True

            # 若有工具调用，回传结果生成最终回复
            if response.tool_calls:
                tool_messages = []
                for tc in response.tool_calls:
                    tool_name = tc["name"]
                    if tool_name == "check_handoff":
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": "需要转人工" if need_human else "不需要转人工",
                        })
                if tool_messages:
                    conversation = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_msg},
                        response.to_message_dict(),
                    ] + tool_messages
                    session_id = state.get("session_id", "")
                    final_text = ""
                    async for chunk in self.llm.astream(conversation):
                        final_text += chunk
                        if session_id:
                            push_token(session_id, chunk)

        # =====================================================================
        # Step 4: 投诉关键词后处理
        # =====================================================================
        complaint_keywords = ["投诉", "退款", "骗人", "诈骗", "差评"]
        for kw in complaint_keywords:
            if kw in user_msg:
                need_human = True
                break

        return {
            "final_reply": final_text,
            "need_human": need_human,
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
