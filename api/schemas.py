"""Pydantic 请求/响应模型"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class ChatRequest(BaseModel):
    """POST /chat 请求体"""
    session_id: str = Field(..., description="会话唯一标识")
    customer_id: str = Field(..., description="客户唯一标识")
    channel: Literal["whatsapp", "wechat", "web", "messenger", "tiktok"] = Field(
        ..., description="消息渠道"
    )
    message: str = Field(..., min_length=1, max_length=4000, description="用户消息")
    language: str = Field(default="zh", description="语言偏好")


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
