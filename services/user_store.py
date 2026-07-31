"""用户数据库操作——最简 CRUD

所有操作通过 SQLAlchemy async engine 直连 MySQL。
表结构见 scripts/migrate_mysql.sql 中的 users / conversations 表。
"""

import logging
from sqlalchemy import text
from services.mysql import get_engine

logger = logging.getLogger(__name__)


class UserStore:
    """用户与对话的数据库操作（无 ORM，原生 SQL）"""

    # =========================================================================
    # 用户
    # =========================================================================

    async def get_user_by_username(self, username: str) -> dict | None:
        """按用户名查找用户"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT user_id, username, password, created_at FROM users WHERE username = :u"),
                {"u": username},
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def create_user(self, user_id: str, username: str, password_hash: str):
        """创建新用户"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO users (user_id, username, password) VALUES (:id, :u, :p)"),
                {"id": user_id, "u": username, "p": password_hash},
            )

    # =========================================================================
    # 对话
    # =========================================================================

    async def list_conversations(self, user_id: str) -> list[dict]:
        """列出用户的所有对话，按更新时间倒序"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT conversation_id, user_id, title, created_at, updated_at "
                    "FROM conversations WHERE user_id = :uid ORDER BY updated_at DESC"
                ),
                {"uid": user_id},
            )
            rows = result.mappings().all()
            return [
                {
                    "conversation_id": r["conversation_id"],
                    "title": r["title"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else "",
                }
                for r in rows
            ]

    async def create_conversation(self, conversation_id: str, user_id: str, title: str = "新对话"):
        """创建新对话"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO conversations (conversation_id, user_id, title) "
                    "VALUES (:cid, :uid, :t)"
                ),
                {"cid": conversation_id, "uid": user_id, "t": title},
            )

    async def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """删除对话（仅所有者可删除），返回是否删除成功"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM conversations WHERE conversation_id = :cid AND user_id = :uid"
                ),
                {"cid": conversation_id, "uid": user_id},
            )
            return result.rowcount > 0

    async def get_conversation(self, conversation_id: str) -> dict | None:
        """获取单个对话信息"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM conversations WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def update_conversation_title(self, conversation_id: str, title: str):
        """更新对话标题"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE conversations SET title = :t WHERE conversation_id = :cid"),
                {"t": title, "cid": conversation_id},
            )
