"""意图路由器——使用结构化输出做四分类（httpx 直连版）

v2: 整合对话历史 + current_branch 上下文，避免跟进消息被误路由。
v3: 预过滤器——能力询问/简单寒暄等高频误判模式，跳过 LLM 直接路由到客服。
v4: Journey Stage 感知——非 discovery 阶段降级为打断检测，不再调用 LLM。
"""

import re
from pydantic import BaseModel, Field
from graph.state import AgentState
from graph.conditions.route_decision import _build_stage_scores
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


# =============================================================================
# v4: 打断检测——非 discovery 阶段的用户意图跳变检测
# =============================================================================

# 投诉/退款——打断销售的绝对信号
_COMPLAINT_INTERRUPT_PATTERNS = [
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
    r"诈骗",
    r"报警",
    r"凭什么.*(?:不退|不给退|拒绝退款)",
]

# 运营相关——在定制/销售阶段提订单/付款
_OP_INTERRUPT_PATTERNS = [
    r"我的订单",
    r"付款.*(?:怎么|确认|了吗)",
    r"(?:订单|酒店).*确认",
    r"支付.*(?:问题|失败|成功)",
    r"退款.*进度",
    r"行程.*(?:取消|退款)",
    r"改签",
    r"联系.*导游",
    r"航班.*(?:取消|延误|改)",
]

# 定制/销售相关——在运营阶段提新行程
_REENGAGE_PATTERNS = [
    r"想去.*(?:北京|西安|上海|成都|广州|桂林|杭州|重庆|昆明|拉萨|三亚|大理|丽江|张家界)",
    r"(?:设计|规划|安排).*(?:行程|路线|方案)",
    r"换个(?:地方|城市|目的地)",
    r"新(?:行程|方案)",
    r"再.*(?:去|设计|规划)",
    r"(?:调整|修改|改|更新).*(?:行程|路线|方案|安排)",
]

# 加购——在运营阶段想继续消费
_REPURCHASE_PATTERNS = [
    r"还想(?:买|订|加|去)",
    r"加购",
    r"再加.*(?:一个|个|一项|项)",
    r"多订",
    r"(?:续住|延长|加天)",
    r"(?:再加|多去).*(?:天|个|城市|景点)",
    r"加(?:一个|个|一|点).*(?:酒店|机票|房间|导游|项目|服务)",
    r"帮我.*(?:加|订|升级|安排).*(?:酒店|机票|房间|导游|服务|项目|门票)",
    r"帮我.*(?:报价|算.*(?:价|钱|费用)|多少钱)",
]


def _detect_interrupt(user_text: str, stage: str, state: AgentState) -> dict | None:
    """检测非 discovery 阶段的用户意图跳变。

    根据当前 journey_stage，判断用户是否想跳转到其他阶段。

    Returns:
        dict 若检测到打断则返回 State 更新；None 表示无打断，保持当前阶段。
    """
    text = user_text.strip()

    # ── 通用：投诉/退款在任何阶段都可能是打断 ──
    for pattern in _COMPLAINT_INTERRUPT_PATTERNS:
        if re.search(pattern, text):
            return {
                "need_human": True,
                "handoff": {
                    "from_agent": "intent_router",
                    "reason": "complaint" if "投诉" in text else "escalation",
                    "priority": "urgent",
                    "summary": f"用户在 {stage} 阶段触发投诉/退款打断：{text[:120]}",
                },
            }

    # ── planning/sales 阶段 → 运营打断 ──
    if stage in ("planning", "sales"):
        for pattern in _OP_INTERRUPT_PATTERNS:
            if re.search(pattern, text):
                return {
                    "journey_stage": "post_purchase",
                    "next_agent": "operations_agent",
                    "intent_scores": _build_stage_scores("post_purchase"),
                    "need_human": False,
                    "agent_traces": [{
                        "agent": "intent_router",
                        "action": "stage_interrupt",
                        "outcome": f"{stage} → post_purchase (运营打断)",
                        "confidence": "high",
                    }],
                }

    # ── post_purchase 阶段 → 定制/销售回流转 ──
    if stage == "post_purchase":
        # 新行程 → 定制
        for pattern in _REENGAGE_PATTERNS:
            if re.search(pattern, text):
                return {
                    "journey_stage": "planning",
                    "next_agent": "trip_planner",
                    "intent_scores": _build_stage_scores("planning"),
                    "need_human": False,
                    "agent_traces": [{
                        "agent": "intent_router",
                        "action": "stage_interrupt",
                        "outcome": "post_purchase → planning (新行程打断)",
                        "confidence": "high",
                    }],
                }
        # 加购 → 销售
        for pattern in _REPURCHASE_PATTERNS:
            if re.search(pattern, text):
                return {
                    "journey_stage": "sales",
                    "next_agent": "sales_agent",
                    "intent_scores": _build_stage_scores("sales"),
                    "need_human": False,
                    "agent_traces": [{
                        "agent": "intent_router",
                        "action": "stage_interrupt",
                        "outcome": "post_purchase → sales (加购打断)",
                        "confidence": "high",
                    }],
                }

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

    v4: Journey Stage 感知。
    - discovery 阶段：完整 LLM 意图分类（含预过滤器）
    - 非 discovery 阶段：打断检测，无打断则透传阶段对应的 intent_scores
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent_scores": {}, "need_human": False}

    last_msg = messages[-1]
    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    if not user_text or not user_text.strip():
        return {
            "intent_scores": _build_stage_scores(state.get("journey_stage", "discovery")),
            "need_human": False,
        }

    journey_stage = state.get("journey_stage", "discovery")

    # ── 通用：预过滤器（能力询问/寒暄，所有阶段生效）──
    prefilter_result = _prefilter_user_message(user_text)
    if prefilter_result is not None:
        if state.get("has_unconverted_trip"):
            prefilter_result["intent_scores"]["sales"] = 0.3
            total = sum(prefilter_result["intent_scores"].values())
            if total > 0:
                for k in prefilter_result["intent_scores"]:
                    prefilter_result["intent_scores"][k] /= total
        if state.get("has_active_order"):
            prefilter_result["intent_scores"]["operations"] = 0.3
            total = sum(prefilter_result["intent_scores"].values())
            if total > 0:
                for k in prefilter_result["intent_scores"]:
                    prefilter_result["intent_scores"][k] /= total
        return prefilter_result

    # ── v4: 非 discovery 阶段——打断检测 ──
    if journey_stage != "discovery":
        interrupt = _detect_interrupt(user_text, journey_stage, state)
        if interrupt:
            return interrupt

        # 无打断 → 保持当前阶段，透传阶段对应的 intent_scores
        return {
            "intent_scores": _build_stage_scores(journey_stage),
            "need_human": False,
            "agent_traces": [{
                "agent": "intent_router",
                "action": "stage_keep",
                "outcome": f"journey_stage={journey_stage}, no interrupt",
                "confidence": "high",
            }],
        }

    # ── discovery 阶段：完整 LLM 意图分类 ──
    current_branch = state.get("current_branch", "")
    history = _build_context_messages(messages)

    system_prompt = load_prompt("intent_router.txt")
    if current_branch:
        system_prompt += (
            f"\n\n**当前会话状态**：用户正在「{current_branch}」分支中。"
            f"若最新消息是该分支的自然延续（补充信息、确认、追问），请大幅提高该分支概率。"
        )

    llm = get_router_llm()
    structured_llm = llm.with_structured_output(IntentResult)

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

    # 有未转化的行程方案时，给 sales 加权
    if state.get("has_unconverted_trip"):
        scores["sales"] = scores["sales"] * 1.5
        total = sum(scores.values())
        if total > 0:
            for k in scores:
                scores[k] /= total

    # 有活跃订单时，给 operations 加权
    if state.get("has_active_order"):
        scores["operations"] = scores.get("operations", 0.1) * 1.5
        total = sum(scores.values())
        if total > 0:
            for k in scores:
                scores[k] /= total

    # discovery 阶段也设置初始 journey_stage（供 route_decision 使用）
    top_key = max(scores, key=scores.get)
    stage_map = {
        "planner": "planning",
        "sales": "sales",
        "operations": "post_purchase",
        "service": "discovery",
    }
    initial_stage = stage_map.get(top_key, "discovery")

    return {
        "intent_scores": scores,
        "need_human": result.need_human,
        "handoff": handoff,
        "journey_stage": initial_stage,
        "agent_traces": [{
            "agent": "intent_router",
            "action": "classified",
            "outcome": f"planner={result.planner:.2f}, service={result.service:.2f}, stage={initial_stage}",
            "confidence": "high" if max(
                result.service, result.sales, result.operations, result.planner
            ) > 0.5 else "low",
        }],
    }
