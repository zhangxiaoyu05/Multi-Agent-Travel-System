"""测试认证——JWT 工具函数 + 注册/登录端点 + get_current_user 依赖

覆盖：
- JWT 编解码（create_token / decode_token）
- 注册：成功 / 重复用户名 / 格式错误
- 登录：成功 / 错误密码 / 不存在用户
- get_current_user 依赖注入：有效 / 缺失 / 格式错误 / 过期
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# =============================================================================
# JWT 工具函数测试（纯函数，无需 Mock）
# =============================================================================


class TestJwtTools:
    """create_token / decode_token"""

    def test_create_and_decode(self):
        """编解码往返：token 能正确解码出原始 payload"""
        from api.auth import create_token, decode_token

        token = create_token("user-abc123", "testuser")
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == "user-abc123"
        assert payload["username"] == "testuser"

    def test_decode_invalid_token(self):
        """非法 token 返回 None"""
        from api.auth import decode_token

        assert decode_token("not.a.valid.token") is None
        assert decode_token("") is None
        assert decode_token("abc") is None

    def test_decode_expired_token(self):
        """过期 token 返回 None"""
        from datetime import datetime, timedelta, timezone
        from jose import jwt
        from api.auth import decode_token, SECRET_KEY, ALGORITHM

        expired_payload = {
            "sub": "user-expired",
            "username": "expired",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=25),
        }
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        assert decode_token(expired_token) is None

    def test_create_token_contains_required_fields(self):
        """token payload 包含必要字段"""
        from api.auth import create_token, decode_token

        token = create_token("user-fields", "fieldsuser")
        payload = decode_token(token)

        assert "sub" in payload
        assert "username" in payload
        assert "exp" in payload
        assert "iat" in payload


# =============================================================================
# get_current_user 依赖注入测试
# =============================================================================


class TestGetCurrentUser:
    """get_current_user FastAPI 依赖"""

    async def test_valid_token_returns_user(self, auth_token):
        """有效 Bearer token 提取 user_id + username"""
        from api.dependencies import get_current_user

        user = await get_current_user(authorization=f"Bearer {auth_token}")
        assert user["user_id"] == "test-user-01"
        assert user["username"] == "testuser"

    async def test_missing_header(self):
        """无 Authorization header → 401"""
        from api.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=None)
        assert exc.value.status_code == 401
        assert "缺少认证令牌" in exc.value.detail

    async def test_invalid_scheme(self):
        """非 Bearer scheme → 401"""
        from api.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization="Basic dGVzdDp0ZXN0")
        assert exc.value.status_code == 401
        assert "格式错误" in exc.value.detail

    async def test_invalid_token(self):
        """伪造 token → 401"""
        from api.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization="Bearer fake-token-here")
        assert exc.value.status_code == 401
        assert "无效或已过期" in exc.value.detail

    async def test_expired_token(self):
        """过期 token → 401"""
        from datetime import datetime, timedelta, timezone
        from jose import jwt
        from api.auth import SECRET_KEY, ALGORITHM
        from api.dependencies import get_current_user

        expired_payload = {
            "sub": "user-expired",
            "username": "expired",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=25),
        }
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)

        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=f"Bearer {expired_token}")
        assert exc.value.status_code == 401


# =============================================================================
# 注册端点测试（基于实际 app + Mock UserStore）
# =============================================================================


class TestRegisterEndpoint:
    """POST /auth/register"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_user_store):
        self.mock_store = mock_user_store

    def get_client(self):
        """Lazy import 避免 import 时触发 build_graph"""
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_register_success(self, mock_user_store):
        """新用户注册成功 → 200 + user_id + token"""
        mock_user_store.get_user_by_username = AsyncMock(return_value=None)

        client = self.get_client()
        resp = client.post("/auth/register", json={
            "username": "newuser123", "password": "123456",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "newuser123"
        assert data["user_id"].startswith("user-")
        assert len(data["token"]) > 20
        assert data["token_type"] == "bearer"

        # 验证 UserStore 被正确调用
        mock_user_store.create_user.assert_called_once()

    def test_register_duplicate_username(self, mock_user_store):
        """重复用户名 → 409"""
        mock_user_store.get_user_by_username = AsyncMock(return_value={
            "user_id": "user-existing", "username": "existing", "password": "...",
        })

        client = self.get_client()
        resp = client.post("/auth/register", json={
            "username": "existing", "password": "123456",
        })

        assert resp.status_code == 409
        assert "已被注册" in resp.json()["detail"]

    def test_register_short_username(self, mock_user_store):
        """用户名 < 3 字符 → 422"""
        client = self.get_client()
        resp = client.post("/auth/register", json={
            "username": "ab", "password": "123456",
        })
        assert resp.status_code == 422

    def test_register_short_password(self, mock_user_store):
        """密码 < 6 字符 → 422"""
        client = self.get_client()
        resp = client.post("/auth/register", json={
            "username": "validuser", "password": "12345",
        })
        assert resp.status_code == 422

    def test_register_invalid_username_chars(self, mock_user_store):
        """用户名含特殊字符 → 422"""
        client = self.get_client()
        resp = client.post("/auth/register", json={
            "username": "user@name!", "password": "123456",
        })
        assert resp.status_code == 422


# =============================================================================
# 登录端点测试（基于实际 app + Mock UserStore）
# =============================================================================


class TestLoginEndpoint:
    """POST /auth/login"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_user_store):
        self.mock_store = mock_user_store

    def get_client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_login_success(self, mock_user_store):
        """正确用户名密码 → 200 + token"""
        import bcrypt
        hashed = bcrypt.hashpw("123456".encode(), bcrypt.gensalt()).decode()

        mock_user_store.get_user_by_username = AsyncMock(return_value={
            "user_id": "user-existing", "username": "testuser",
            "password": hashed,
        })

        client = self.get_client()
        resp = client.post("/auth/login", json={
            "username": "testuser", "password": "123456",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["user_id"] == "user-existing"
        assert len(data["token"]) > 20

    def test_login_wrong_password(self, mock_user_store):
        """错误密码 → 401"""
        import bcrypt
        hashed = bcrypt.hashpw("right-password".encode(), bcrypt.gensalt()).decode()

        mock_user_store.get_user_by_username = AsyncMock(return_value={
            "user_id": "user-x", "username": "testuser", "password": hashed,
        })

        client = self.get_client()
        resp = client.post("/auth/login", json={
            "username": "testuser", "password": "wrong-password",
        })

        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]

    def test_login_nonexistent_user(self, mock_user_store):
        """不存在用户 → 401"""
        mock_user_store.get_user_by_username = AsyncMock(return_value=None)

        client = self.get_client()
        resp = client.post("/auth/login", json={
            "username": "nobody", "password": "123456",
        })

        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]
