"""FastAPI 依赖注入——从请求中提取当前用户"""

from fastapi import HTTPException, Depends, Header
from api.auth import decode_token


async def get_current_user(authorization: str = Header(None)) -> dict:
    """从 Authorization: Bearer <token> 中解析当前用户

    Usage:
        @app.post("/chat")
        async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
            ...
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证令牌")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="认证格式错误，应为 Bearer <token>")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    return {"user_id": payload["sub"], "username": payload.get("username", "")}
