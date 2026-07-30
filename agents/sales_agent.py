"""销售 Agent——产品推介 + 报价生成 + 签约引导

SalesAgent 负责处理销售类用户消息：
1. 理解客户购买意向，推荐合适产品
2. 调用 quote_price 生成报价单
3. 调用 query_inventory 查询库存
4. 评估购买意向等级，引导签约或培育
"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_quote import quote_price
from tools.mock_inventory import query_inventory
from services.llm import get_agent_llm
from prompts import load_prompt


class SalesAgent(BaseAgent):
    """销售 Agent

    使用 LLM + Tools 模式处理销售咨询。
    tools 中包含 quote_price 和 query_inventory。
    """

    def __init__(self):
        llm = get_agent_llm()
        tools = [quote_price, query_inventory]
        system_prompt = load_prompt("sales_agent.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    def run(self, state: AgentState) -> dict:
        """处理销售咨询

        流程：
        1. 提取用户消息
        2. LLM 决策：直接回复 or 调用工具（报价/查库存）
        3. 处理工具调用结果
        4. 评估客户意向等级（high/mid/low）

        Args:
            state: 当前 AgentState

        Returns:
            dict 包含 final_reply, need_human, intent_level, next_action
        """
        user_msg = self._get_user_message(state)

        if not user_msg:
            return {
                "final_reply": "您好！我是您的专属旅行顾问，有什么旅行产品需要了解的吗？",
                "need_human": False,
                "intent_level": "mid",
                "next_action": "revise",
            }

        # Step 1: LLM 决策 —— 调用工具或直接回复
        llm_with_tools = self.llm.bind_tools(self.tools)

        response = llm_with_tools.invoke([
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ])

        # Step 2: 处理工具调用
        need_human = False
        quote_result = ""
        inventory_result = ""

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                if tool_name == "quote_price":
                    quote_result = quote_price.invoke(tool_args)
                elif tool_name == "query_inventory":
                    inventory_result = query_inventory.invoke(tool_args)

        # Step 3: 如果有工具调用，把结果回传给 LLM 生成最终回复
        if response.tool_calls:
            tool_messages = []
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                if tool_name == "quote_price" and quote_result:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": quote_result,
                    })
                elif tool_name == "query_inventory" and inventory_result:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": inventory_result,
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

        # Step 4: 评估客户意向 —— 基于回复内容关键词
        intent_level, next_action = self._score_intent(user_msg, final_text)

        # Step 5: 检测是否需要转人工（投诉/退款等关键词）
        complaint_keywords = ["投诉", "退款", "骗人", "诈骗", "差评", "太贵了不买"]
        for kw in complaint_keywords:
            if kw in user_msg:
                need_human = True
                break

        return {
            "final_reply": final_text,
            "need_human": need_human,
            "intent_level": intent_level,
            "next_action": next_action,
        }

    # =========================================================================
    # 私有方法
    # =========================================================================

    def _score_intent(self, user_msg: str, reply_text: str) -> tuple:
        """基于用户消息和 AI 回复评估客户购买意向

        使用关键词匹配做快速评分（无需额外 LLM 调用）。

        Returns:
            (intent_level, next_action) 元组
        """
        combined = user_msg + " " + reply_text

        # 高意向信号
        high_signals = [
            "预订", "购买", "签约", "支付", "下单", "就这个", "可以",
            "不错", "满意", "确认", "锁定", "定金", "怎么付款",
            "什么时候出发", "帮我订",
        ]
        # 中意向信号
        mid_signals = [
            "考虑", "再看看", "优惠", "折扣", "对比", "有没有更便宜",
            "能不能便宜", "涨价", "还能加什么",
        ]
        # 低意向信号
        low_signals = [
            "算了", "太贵", "不要", "取消", "放弃", "超出预算",
            "再想想", "不需要",
        ]

        high_count = sum(1 for s in high_signals if s in combined)
        mid_count = sum(1 for s in mid_signals if s in combined)
        low_count = sum(1 for s in low_signals if s in combined)

        if low_count > high_count and low_count > mid_count:
            return ("low", "give_up")
        elif high_count >= mid_count and high_count > low_count:
            return ("high", "accept")
        elif mid_count > 0:
            return ("mid", "revise")
        else:
            # 默认：有报价生成 → 中意向培育；无报价 → 继续了解
            if "报价单" in reply_text or "报价" in reply_text:
                return ("mid", "revise")
            return ("mid", "revise")


# 模块级单例
_agent_instance: SalesAgent | None = None


def get_sales_agent() -> SalesAgent:
    """获取销售 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SalesAgent()
    return _agent_instance
