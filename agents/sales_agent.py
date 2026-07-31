"""销售 Agent——产品推介 + 报价生成 + 签约引导

使用 BaseAgent 内置的 _run_tool_calling_loop 处理标准 tool-calling 流程。
在此基础上添加意向评分和投诉检测的后处理逻辑。
"""

from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_quote import quote_price
from tools.mock_inventory import query_inventory
from services.llm import get_agent_llm
from prompts import load_prompt


class SalesAgent(BaseAgent):
    """销售 Agent——报价 + 库存 + 意向评分"""

    def __init__(self):
        llm = get_agent_llm()
        tools = [quote_price, query_inventory]
        system_prompt = load_prompt("sales_agent.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    async def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        language = self._get_language(state)

        if not user_msg:
            return {
                "final_reply": "您好！我是您的专属旅行顾问，有什么旅行产品需要了解的吗？",
                "need_human": False,
                "intent_level": "mid",
                "next_action": "revise",
            }

        # 标准 tool-calling 循环
        loop_result = await self._run_tool_calling_loop(user_msg, language=language)
        final_text = loop_result["final_text"]
        need_human = loop_result["need_human"]

        # 意向评分（基于关键词）
        intent_level, next_action = self._score_intent(user_msg, final_text)

        # 投诉关键词检测
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

    def _score_intent(self, user_msg: str, reply_text: str) -> tuple[str, str]:
        """基于关键词评估购买意向"""
        combined = user_msg + " " + reply_text

        high_signals = [
            "预订", "购买", "签约", "支付", "下单", "就这个", "可以",
            "不错", "满意", "确认", "锁定", "定金", "怎么付款",
            "什么时候出发", "帮我订",
        ]
        mid_signals = [
            "考虑", "再看看", "优惠", "折扣", "对比", "有没有更便宜",
            "能不能便宜", "涨价", "还能加什么",
        ]
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
            if "报价单" in reply_text or "报价" in reply_text:
                return ("mid", "revise")
            return ("mid", "revise")


_agent_instance: SalesAgent | None = None


def get_sales_agent() -> SalesAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SalesAgent()
    return _agent_instance
