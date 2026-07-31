"""认证路由——最简登录/注册 + JWT 签发

规则：
    - 用户名：3-20 位字母数字
    - 密码：≥ 6 位
    - 无邮箱、无验证码、无 OAuth
"""

import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from jose import jwt, JWTError
import bcrypt
from services.user_store import UserStore

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "travel-agent-dev-secret-key-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

router = APIRouter(prefix="/auth", tags=["auth"])


# =============================================================================
# 请求/响应模型
# =============================================================================


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    password: str = Field(..., min_length=6, max_length=100)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名只能包含字母、数字、下划线和连字符")
        return v


class AuthResponse(BaseModel):
    user_id: str
    username: str
    token: str
    token_type: str = "bearer"


# =============================================================================
# JWT 工具
# =============================================================================


def create_token(user_id: str, username: str) -> str:
    """签发 JWT access token"""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解码 JWT，失败返回 None"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# =============================================================================
# 路由
# =============================================================================


@router.post("/register", response_model=AuthResponse)
async def register(req: AuthRequest):
    """注册新用户

    成功返回 user_id + token，前端自动登录。
    用户名重复返回 409。
    """
    store = UserStore()

    # 检查用户名是否已存在
    existing = await store.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已被注册")

    # 创建用户
    user_id = f"user-{uuid.uuid4().hex[:12]}"
    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    await store.create_user(user_id, req.username, hashed)

    token = create_token(user_id, req.username)
    logger.info(f"User registered: {req.username} ({user_id})")

    return AuthResponse(user_id=user_id, username=req.username, token=token)


@router.post("/login", response_model=AuthResponse)
async def login(req: AuthRequest):
    """用户登录

    验证用户名密码，成功返回 token。
    失败返回 401。
    """
    store = UserStore()
    user = await store.get_user_by_username(req.username)

    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not bcrypt.checkpw(req.password.encode(), user["password"].encode()):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_token(user["user_id"], user["username"])
    logger.info(f"User logged in: {req.username}")

    return AuthResponse(user_id=user["user_id"], username=user["username"], token=token)
