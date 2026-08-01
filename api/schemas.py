"""Pydantic 请求/响应模型"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class ChatRequest(BaseModel):
    """POST /chat 和 /chat/stream 请求体

    customer_id 由后端从 JWT token 注入，前端无需传递。
    session_id 已重命名为 conversation_id，语义更清晰。
    """
    conversation_id: str = Field(..., description="对话唯一标识")
    message: str = Field(..., min_length=1, max_length=4000, description="用户消息")
    channel: Literal["whatsapp", "wechat", "web", "messenger", "tiktok"] = Field(
        default="web", description="消息渠道"
    )
    language: str = Field(default="zh", description="语言偏好")
    mode: str = Field(default="planner", description="planner=行程定制, support=智能客服")


class TripDraftResponse(BaseModel):
    """行程草案"""
    version: int
    itinerary_md: str
    estimated_cost: Optional[str] = None
    weather_summary: Optional[str] = None


class QuoteResponse(BaseModel):
    """报价单"""
    total_per_person: Optional[str] = None
    breakdown: Optional[str] = None


class ChatResponse(BaseModel):
    """POST /chat 响应体"""
    reply: str = Field(..., description="AI 回复内容")
    current_branch: Optional[str] = Field(None, description="当前分支")
    draft: Optional[TripDraftResponse] = None
    quote: Optional[QuoteResponse] = None
    need_human: bool = Field(default=False, description="是否需要转人工")
    intent_scores: Optional[dict] = None


class ConversationItem(BaseModel):
    """对话列表项"""
    conversation_id: str
    title: str
    created_at: str
    updated_at: str


class CreateConversationRequest(BaseModel):
    """新建对话请求"""
    title: str = Field(default="新对话", max_length=200)


class CreateConversationResponse(BaseModel):
    """新建对话响应"""
    conversation_id: str
    title: str


# =============================================================================
# 记忆系统——短/中/长期记忆模型
# =============================================================================


class BudgetRange(BaseModel):
    """预算区间"""
    min: Optional[int] = None
    max: Optional[int] = None
    currency: str = "USD"


class UserProfileResponse(BaseModel):
    """GET /profile 响应——用户画像完整数据"""
    user_id: str
    username: str
    # 基本信息
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    # 旅行身份
    nationality: Optional[str] = None
    passport_country: Optional[str] = None
    preferred_language: str = "zh"
    # 深度旅行偏好
    preferred_destinations: list[str] = Field(default_factory=list)
    budget_range: Optional[BudgetRange] = None
    travel_style: Optional[str] = None          # 轻松/适中/紧凑
    interests: list[str] = Field(default_factory=list)
    travel_companion: Optional[str] = None      # solo/family/couple/friends
    special_needs: list[str] = Field(default_factory=list)
    preferred_seasons: list[str] = Field(default_factory=list)
    # LLM 待确认建议
    suggested_fields: Optional[dict] = None
    # 元数据
    source: str = "manual"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_active_at: Optional[str] = None


class UserProfileUpdateRequest(BaseModel):
    """PUT /profile 请求——用户手动编辑画像"""
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    nationality: Optional[str] = None
    passport_country: Optional[str] = None
    preferred_language: Optional[str] = None
    preferred_destinations: Optional[list[str]] = None
    budget_range: Optional[BudgetRange] = None
    travel_style: Optional[str] = None
    interests: Optional[list[str]] = None
    travel_companion: Optional[str] = None
    special_needs: Optional[list[str]] = None
    preferred_seasons: Optional[list[str]] = None
    # 是否同时接受 LLM 建议
    accept_suggestions: bool = False


class PendingUpdateResponse(BaseModel):
    """LLM 建议的用户偏好更新项"""
    field: str
    current_value: Optional[str] = None
    suggested_value: Optional[str] = None
    confidence: float = 0.5
    reason: Optional[str] = None


class PreferenceSnapshotResponse(BaseModel):
    """中期记忆偏好快照"""
    id: int
    source_conversation_id: Optional[str] = None
    preferred_destinations: list[str] = Field(default_factory=list)
    budget_range: Optional[str] = None
    travel_style: Optional[str] = None
    interests: list[str] = Field(default_factory=list)
    travel_companion: Optional[str] = None
    special_needs: Optional[str] = None
    preferred_seasons: Optional[str] = None
    confidence: float = 0.5
    is_promoted: bool = False
    created_at: Optional[str] = None
    expire_at: Optional[str] = None


class ChatMessageItem(BaseModel):
    """单条历史消息"""
    role: str                        # user / agent
    content: str
    branch: Optional[str] = None
    intent_scores: Optional[dict] = None
    created_at: Optional[str] = None


class ConversationMessagesResponse(BaseModel):
    """GET /conversations/{id}/messages 增强响应"""
    conversation_id: str
    messages: list[ChatMessageItem]
    summary: Optional[str] = None
