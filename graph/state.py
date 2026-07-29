"""AgentState——全局共享的会话状态

这是整个系统的数据契约，所有节点共享同一个 State。
继承 LangGraph 的 MessagesState（自带消息管理和 add_messages reducer），
扩展业务字段。
"""

from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages
from langgraph.graph import MessagesState


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


# =============================================================================
# 主 State
# =============================================================================


class AgentState(MessagesState):
    """
    全局共享 State。

    继承 MessagesState → 自带 messages 字段和 add_messages reducer，
    messages 会自动累积历史消息。

    所有节点返回 dict[str, Any]，LangGraph 自动合并到 State。
    """

    # ---- 渠道与会话 ----
    session_id: str           # 会话唯一标识
    customer_id: str          # 客户唯一标识
    channel: str              # whatsapp / wechat / web / messenger / tiktok
    language: str             # zh / en / ja / ko（默认 zh）

    # ---- 路由 ----
    current_branch: str       # service / sales / operations / planner
    intent_scores: dict       # {"service": 0.1, "sales": 0.05, ...}

    # ---- 业务数据 ----
    need: TripNeed            # 客户出行需求
    draft: TripDraft          # 行程草案
    revision_count: int       # 修订次数，硬上限 3
    intent_level: str         # high / mid / low

    # ---- 控制 ----
    need_human: bool          # 是否需要转人工
    next_action: str          # revise / accept / give_up

    # ---- 输出 ----
    final_reply: str          # 最终回复文本
    quote: str                # 报价单文本
