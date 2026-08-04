"""意图路由器——使用结构化输出做四分类（httpx 直连版）

v2: 整合对话历史 + current_branch 上下文，避免跟进消息被误路由。
v3: 预过滤器——能力询问/简单寒暄等高频误判模式，跳过 LLM 直接路由到客服。
"""

import re
from pydantic import BaseModel, Field
from graph.state import AgentState
from services.llm import get_router_llm
from prompts import load_prompt

# 注入到 LLM 上下文的历史消息条数（用户 + AI 交替）
_CONTEXT_WINDOW = 6

# =============================================================================
# 预过滤器：匹配明确的简单意图，跳过 LLM 调用（避免 LLM 误判 need_human）
# =============================================================================

# 能力询问类：问系统能干什么、有什么功能
_CAPABILITY_PATTERNS = [
    r"你能[干做]?什么",
    r"你有(什么|哪些?)功能",
    r"你能[干做]吗",
    r"你[有会]?什么[能力用处]",
    r"你[可会]以[干做]什么",
    r"你能帮[助我][干做]什么",
    r"你支持什么",
    r"你有什么服务",
    r"怎么用[你啊]",
    r"使用[说明帮助]",
    r"[有什么]?功能[介绍说明]",
    r"how.*(?:can|do).*you.*(?:help|do|work)",
    r"what.*(?:can|do).*you.*(?:do|help)",
    r"help",
]

# 寒暄/自我介绍类
_GREETING_PATTERNS = [
    r"^(你好|hi|hello|嗨|hey)[!！。.]*$",
    r"^(你是谁|你是[谁什么])[?？!！。.]*$",
    r"^(你是)?(做什么的|干什么的)[?？!！。.]*$",
    r"^(早上好|下午好|晚上好|早安|晚安)[!！。.]*$",
    r"^在[吗嘛不]?[?？!！。.]*$",
    r"^(感谢|谢谢|多谢|thanks?)[!！。.]*$",
]

# 投诉/退款触发词（用于预检——但能力询问不走此逻辑）
_OBVIOUS_COMPLAINT_WORDS = ["投诉", "退款", "差评", "我要投诉", "找你们领导", "骗子", "坑人"]

# 明确投诉意图的完整模式（区别于 FAQ 咨询如"投诉流程是什么"）
_OBVIOUS_COMPLAINT_PATTERNS = [
    r"我要投诉",
    r"我想投诉",
    r"我要退款",
    r"给我退款",
    r"要求退款",
    r"找你们领导",
    r"叫.*(?:领导|经理|负责人)",
    r"(?:太|很|非常|特别)(?:差|烂|坑|糟糕)",
    r"骗子",
    r"坑人",
    r"(?:凭什么|为什么).*(?:不退|不给退|拒绝退款)",
]

def _has_complaint_intent(user_text: str) -> bool:
    """检查用户消息是否表达明确的投诉/退款意图（非 FAQ 查询）。"""
    text = user_text.strip()
    for pattern in _OBVIOUS_COMPLAINT_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

def _prefilter_user_message(user_text: str) -> dict | None:
    """预检用户消息，若匹配明确的简单意图则直接返回结果（跳过 LLM）。

    解决的问题：
    - "你能干什么" 被 LLM 误判为 need_human=true（严重误导）
    - 简单寒暄被误分类

    Returns:
        dict 若匹配则直接返回的结果；None 表示需要走 LLM 正常路由。
    """
    text = user_text.strip().lower()

    # 1. 能力询问 → service 高分，绝不转人工
    for pattern in _CAPABILITY_PATTERNS:
        if re.search(pattern, text):
            return {
                "intent_scores": {"service": 0.95, "sales": 0.0, "operations": 0.0, "planner": 0.05},
                "need_human": False,
                "handoff": {},
                "agent_traces": [{
                    "agent": "intent_router",
                    "action": "classified",
                    "outcome": "planner=0.05, service=0.95",
                    "confidence": "high",
                }],
            }

    # 2. 寒暄 → service 高分
    for pattern in _GREETING_PATTERNS:
        if re.search(pattern, text):
            return {
                "intent_scores": {"service": 0.90, "sales": 0.0, "operations": 0.0, "planner": 0.10},
                "need_human": False,
                "handoff": {},
                "agent_traces": [{
                    "agent": "intent_router",
                    "action": "classified",
                    "outcome": "planner=0.10, service=0.90",
                    "confidence": "high",
                }],
            }

    # 3. 明确的投诉/退款关键词预检（仅用于优先标记，仍然走 LLM 精确判断）
    #    注意：不在此处返回，仅记录。LLM 做最终判断。
    #    （这里只是预防性注释，实际上预检不拦截投诉，让 LLM 正常判断）

    return None


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

    # ---- 预过滤器：明确的简单意图跳过 LLM（v3） ----
    prefilter_result = _prefilter_user_message(user_text)
    if prefilter_result is not None:
        # Phase 20: 即使匹配预过滤器，如果有未转化行程也提高 sales 权重
        if state.get("has_unconverted_trip"):
            prefilter_result["intent_scores"]["sales"] = 0.3
            # 重新归一化
            total = sum(prefilter_result["intent_scores"].values())
            if total > 0:
                for k in prefilter_result["intent_scores"]:
                    prefilter_result["intent_scores"][k] /= total
        return prefilter_result

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

    handoff = {}
    if result.need_human:
        # 优先级判断：明确的投诉/退款关键词 → urgent；其他 → normal
        is_urgent = _has_complaint_intent(user_text)
        handoff = {
            "from_agent": "intent_router",
            "reason": "user_request",
            "priority": "urgent" if is_urgent else "normal",
            "summary": f"用户消息被 LLM 判定为需转人工：{result.reasoning[:120]}",
        }

    scores = {
        "service": result.service,
        "sales": result.sales,
        "operations": result.operations,
        "planner": result.planner,
    }

    # Phase 20: 有未转化的行程方案时，给 sales 加权
    if state.get("has_unconverted_trip"):
        scores["sales"] = scores["sales"] * 1.5
        # 重新归一化
        total = sum(scores.values())
        if total > 0:
            for k in scores:
                scores[k] /= total

    return {
        "intent_scores": scores,
        "need_human": result.need_human,
        "handoff": handoff,
        "agent_traces": [{
            "agent": "intent_router",
            "action": "classified",
            "outcome": f"planner={result.planner:.2f}, service={result.service:.2f}",
            "confidence": "high" if max(
                result.service, result.sales, result.operations, result.planner
            ) > 0.5 else "low",
        }],
    }
