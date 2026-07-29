"""意图路由器——使用 LangChain 结构化输出（Phase 2）

调用轻量 LLM 分析用户消息，输出四类意图概率 + 是否转人工。
使用 with_structured_output 做可靠的结构化输出，替代裸 json.loads。
"""

from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm
from prompts import load_prompt


# =============================================================================
# LLM 结构化输出 Schema
# =============================================================================


class IntentResult(BaseModel):
    """LLM 意图路由的结构化输出 Schema"""

    service: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="客服意图概率（FAQ、订单、退改、签证等）"
    )
    sales: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="销售意图概率（询价、购买、签约等）"
    )
    operations: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="运营意图概率（入驻、履约、工单等）"
    )
    planner: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="定制意图概率（行程规划、目的地推荐等）"
    )
    need_human: bool = Field(
        default=False,
        description="是否需要立即转人工（投诉/退款类）"
    )
    reasoning: str = Field(
        default="",
        description="简短判断原因"
    )


# =============================================================================
# 节点函数
# =============================================================================


def intent_router(state: AgentState) -> dict:
    """分析用户消息，输出意图分数和转人工判断

    使用 with_structured_output 确保输出格式可靠，
    避免 JSON 解析失败导致的异常。

    Args:
        state: 当前 AgentState

    Returns:
        {"intent_scores": {...}, "need_human": bool}
        current_branch 由条件边 route_decision 设置
    """
    messages = state.get("messages", [])
    if not messages:
        return {
            "intent_scores": {},
            "need_human": False,
        }

    # 获取最后一条用户消息
    last_msg = messages[-1]
    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    if not user_text or not user_text.strip():
        return {
            "intent_scores": {"service": 1.0, "sales": 0.0, "operations": 0.0, "planner": 0.0},
            "need_human": False,
        }

    # 初始化 LLM 并绑定结构化输出
    llm = get_router_llm()
    structured_llm = llm.with_structured_output(IntentResult)
    system_prompt = load_prompt("intent_router.txt")

    try:
        result: IntentResult = structured_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ])
    except Exception:
        # LLM 调用失败 → 兜底：进客服
        result = IntentResult(
            service=1.0, sales=0.0, operations=0.0, planner=0.0,
            need_human=False, reasoning="LLM invocation error, fallback to service"
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
