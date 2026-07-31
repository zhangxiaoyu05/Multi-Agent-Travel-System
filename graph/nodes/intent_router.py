"""意图路由器——使用结构化输出做四分类（httpx 直连版）

v2: 整合对话历史 + current_branch 上下文，避免跟进消息被误路由。
"""

from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm
from prompts import load_prompt

# 注入到 LLM 上下文的历史消息条数（用户 + AI 交替）
_CONTEXT_WINDOW = 6


class IntentResult(BaseModel):
    """LLM 意图路由的结构化输出 Schema"""
    service: float = Field(default=0.0, ge=0.0, le=1.0, description="客服意图概率")
    sales: float = Field(default=0.0, ge=0.0, le=1.0, description="销售意图概率")
    operations: float = Field(default=0.0, ge=0.0, le=1.0, description="运营意图概率")
    planner: float = Field(default=0.0, ge=0.0, le=1.0, description="定制意图概率")
    need_human: bool = Field(default=False, description="是否需要立即转人工")
    reasoning: str = Field(default="", description="简短判断原因")


def _build_context_messages(messages: list, max_count: int = _CONTEXT_WINDOW) -> list[dict]:
    """将最近的 N 条消息转换为 LLM 上下文格式。

    只保留人类和 AI 消息（跳过 System / Tool），并截断过长内容。
    """
    ctx = []
    for msg in messages[-max_count * 2:]:  # 多取一些再过滤
        role = None
        if hasattr(msg, "type"):
            if msg.type == "human":
                role = "user"
            elif msg.type == "ai":
                role = "assistant"
        if role is None:
            continue

        content = msg.content if hasattr(msg, "content") else str(msg)
        if len(content) > 500:
            content = content[:500] + "…"
        ctx.append({"role": role, "content": content})

    return ctx[-max_count:]


def intent_router(state: AgentState) -> dict:
    """分析用户消息，输出意图分数和转人工判断（同步，无异步调用）

    与 v1 的关键区别：把对话历史 + current_branch 传给 LLM，
    让模型知道"用户正在一个定制流程中补充信息"，而非独立判断。
    """
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

    # ---- 构建上下文 ----
    current_branch = state.get("current_branch", "")
    history = _build_context_messages(messages)

    # 把上下文信息嵌入 system prompt
    system_prompt = load_prompt("intent_router.txt")
    if current_branch:
        system_prompt += (
            f"\n\n**当前会话状态**：用户正在「{current_branch}」分支中。"
            f"若最新消息是该分支的自然延续（补充信息、确认、追问），请大幅提高该分支概率。"
        )

    llm = get_router_llm()
    structured_llm = llm.with_structured_output(IntentResult)

    # 组合调用：system + 历史 + 最新消息
    invoke_messages = [{"role": "system", "content": system_prompt}]
    invoke_messages.extend(history)

    try:
        result: IntentResult = structured_llm.invoke(invoke_messages)
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
