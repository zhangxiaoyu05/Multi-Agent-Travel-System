"""AgentState——全局共享的会话状态

这是整个系统的数据契约，所有节点共享同一个 State。
继承 LangGraph 的 MessagesState（自带消息管理和 add_messages reducer），
扩展业务字段。

=== 字段所有权契约 ===
| 字段 | 写入节点（owner） | 读取节点 |
|------|-------------------|----------|
| session_id/customer_id/channel/language | session_context | 所有 |
| user_profile/user_preferences | session_context | 所有 |
| original_query | query_rewrite | intent_router, 调试/审计 |
| intent_scores | intent_router | route_decision, human_handoff |
| current_branch | 各 Agent 节点 | route_decision, human_handoff |
| need | trip_planner | trip_planner, human_handoff, operations_sync |
| draft | trip_planner | intent_scorer, human_handoff, operations_sync |
| revision_count | revision_loop | trip_planner, intent_scorer, revision_decision |
| quote | sales_agent | human_handoff |
| intent_level/next_action | intent_scorer(定制), sales_agent(销售) | revision_decision, after_sales |
| sales_pipeline_stage | sales_agent | after_sales, session_context |
| sales_context | sales_agent | sales_agent（跨会话） |
| has_unconverted_trip + previous_draft_id | session_context | intent_router, sales_agent |
| goto_planner | sales_agent | after_sales |
| need_human + handoff | 需转人工的 Agent | route_decision, human_handoff |
| final_reply | 各 Agent | API 层 |
| agent_traces | 所有 Agent（追加） | 调试/监控 |
| branch_history | route_decision（追加） | 调试/分析 |
"""

from typing import TypedDict, Annotated
from langgraph.graph import MessagesState


# =============================================================================
# 自定义 Reducer（追加不覆盖）
# =============================================================================

def _append_list(existing: list | None, new: list) -> list:
    """合并列表——用于 agent_traces / branch_history 等追加型字段。

    LangGraph 对每个 State 字段支持自定义 reducer。
    这里实现 append-only：新值追加到现有列表末尾，不存在则创建。
    """
    return (existing or []) + new


# =============================================================================
# 嵌套结构
# =============================================================================


class TripNeed(TypedDict, total=False):
    """客户出行需求——字段在多轮对话中逐步填充"""

    destination: str          # 目的地城市
    days: int                 # 行程天数
    arrival_date: str         # 抵达日期 YYYY-MM-DD
    pax: int                  # 人数
    budget: str               # 预算（带币种，如 "$2000" 或 "¥5000"）
    theme: str                # 偏好主题（历史文化 / 自然风光 / 美食 / 综合）
    pace: str                 # 节奏偏好（轻松 / 适中 / 紧凑）
    special_requests: str     # 特殊需求（轮椅、儿童座椅、素食等）


class TripDraft(TypedDict, total=False):
    """行程草案"""

    version: int              # 版本号（每次修订 +1）
    itinerary_md: str         # Markdown 格式行程
    estimated_cost: str       # 预估人均费用
    weather_summary: str      # 天气摘要


class HandoffContext(TypedDict, total=False):
    """转人工交接上下文——解释为什么转、谁触发、紧急程度。

    替代裸 need_human=True 判断，让 human_handoff 能够生成精准的交接单。
    """
    from_agent: str           # 触发转人工的来源 Agent
    reason: str               # "complaint" | "escalation" | "give_up" | "user_request" | "faq_not_covered"
    priority: str             # "normal" | "urgent"
    summary: str              # 简短摘要（1-2 句话）


class AgentTrace(TypedDict, total=False):
    """单个 Agent 的执行审计记录——追加到 agent_traces 列表"""
    agent: str                # "intent_router" | "trip_planner" | "customer_service" | ...
    action: str               # "classified" | "generated_draft" | "answered_faq" | ...
    outcome: str              # "routed_to_planner" | "draft_v2_generated" | ...
    confidence: str           # "high" | "mid" | "low"


# =============================================================================
# 主 State
# =============================================================================


class AgentState(MessagesState):
    """
    全局共享 State。

    继承 MessagesState → 自带 messages 字段和 add_messages reducer，
    messages 会自动累积历史消息。

    所有节点返回 dict[str, Any]，LangGraph 自动合并到 State。

    设计原则：
    - 每个字段有明确的 owner（写入节点）
    - 追加型字段（agent_traces, branch_history）使用 _append_list reducer
    - 分支切换时重置上一个分支的控制信号（避免跨分支污染）
    """

    # ====== 会话元数据（owner: session_context，之后只读）======
    session_id: str           # 会话唯一标识
    customer_id: str          # 客户唯一标识
    channel: str              # whatsapp / wechat / web / messenger / tiktok
    language: str             # zh / en / ja / ko（默认 zh）

    # ====== 查询改写（owner: query_rewrite）======
    original_query: str       # 用户原始输入（改写前），用于调试和审计

    # ====== 路由（owner: intent_router）======
    current_branch: str       # service / sales / operations / planner
    intent_scores: dict       # {"service": 0.1, "sales": 0.05, ...}
    force_branch: str         # 强制路由目标（support 模式设为 "customer_service"），跳过意图识别

    # ====== 业务数据 ======
    need: TripNeed            # 客户出行需求（owner: trip_planner）
    draft: TripDraft          # 行程草案（owner: trip_planner）
    quote: str                # 结构化报价文本（owner: sales_agent）
    revision_count: int       # 修订次数，硬上限 3（owner: revision_loop）

    # ====== 控制信号 ======
    need_human: bool          # 是否需要转人工（由触发 Agent 设置）
    handoff: HandoffContext   # 🆕 转人工上下文——替代裸 need_human 判断
    intent_level: str         # 意向等级（owner: intent_scorer(定制流) / sales_agent(销售流)）
    next_action: str          # 下一步动作（owner: intent_scorer(定制流) / sales_agent(销售流)）

    # ====== 销售 Pipeline（owner: sales_agent）======
    sales_pipeline_stage: str  # lead/qualified/negotiation/closing/won/lost
    sales_context: dict        # {followup_count, discount_offered, last_stage_entered_at, ...}
    has_unconverted_trip: bool # 是否有未转化的行程方案（session_context 写入）
    previous_draft_id: str     # 上一份行程方案标识（session_context 写入）
    goto_planner: bool         # 销售中用户要求修改行程 → 路由到 trip_planner

    # ====== 输出 ======
    final_reply: str          # 面向用户的最终回复

    # ====== 🧠 用户记忆（owner: session_context，之后只读）======
    user_profile: dict          # 长期画像（user_profiles 表）
    user_preferences: dict      # 中期偏好快照（user_preferences 表最新一条）

    # ====== 🆕 审计与追踪 ======
    agent_traces: Annotated[list[dict], _append_list]      # Agent 执行日志（追加）
    branch_history: Annotated[list[dict], _append_list]    # 用户分支路径（追加）
