"""意图路由器——使用结构化输出做四分类（httpx 直连版）"""

from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm
from prompts import load_prompt


class IntentResult(BaseModel):
    """LLM 意图路由的结构化输出 Schema"""
    service: float = Field(default=0.0, ge=0.0, le=1.0, description="客服意图概率")
    sales: float = Field(default=0.0, ge=0.0, le=1.0, description="销售意图概率")
    operations: float = Field(default=0.0, ge=0.0, le=1.0, description="运营意图概率")
    planner: float = Field(default=0.0, ge=0.0, le=1.0, description="定制意图概率")
    need_human: bool = Field(default=False, description="是否需要立即转人工")
    reasoning: str = Field(default="", description="简短判断原因")


def intent_router(state: AgentState) -> dict:
    """分析用户消息，输出意图分数和转人工判断（同步，无异步调用）"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent_scores": {}, "need_human": False}

    last_msg = messages[-1]
    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    if not user_text or not user_text.strip():
        return {
            "intent_scores": {"service": 1.0, "sales": 0.0, "operations": 0.0, "planner": 0.0},
            "need_human": False,
        }

    llm = get_router_llm()
    structured_llm = llm.with_structured_output(IntentResult)
    system_prompt = load_prompt("intent_router.txt")

    try:
        result: IntentResult = structured_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ])
    except Exception:
        result = IntentResult(
            service=1.0, sales=0.0, operations=0.0, planner=0.0,
            need_human=False, reasoning="LLM error fallback",
        )

    return {
        "intent_scores": {
            "service": result.service,
            "sales": result.sales,
            "operations": result.operations,
            "planner": result.planner,
        },
        "need_human": result.need_human,
    }
