"""记忆管理器——短/中/长期记忆统一数据访问层

负责：
- 短期记忆：对话消息 Redis 缓存 + MySQL 持久化 + 上下文窗口管理
- 中期记忆：LLM 偏好提取 + 快照存储（30-90 天 TTL）
- 长期记忆：用户画像 CRUD + LLM 建议

数据流：
    用户消息 → Redis 即时缓存 → MySQL 异步持久化
    上下文溢出 → LLM 摘要生成 → MySQL + Redis 摘要存储
    对话结束 → LLM 偏好提取 → MySQL user_preferences
    LLM 建议 → user_profiles.suggested_fields → 用户确认

使用方式：
    from services.memory import MemoryManager
    mm = MemoryManager()
    await mm.save_message(conv_id, role, content)
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from services.mysql import get_engine

logger = logging.getLogger(__name__)


class MemoryManager:
    """三层记忆系统统一管理"""

    # =========================================================================
    # 短期记忆——对话消息
    # =========================================================================

    async def save_message(
        self, conversation_id: str, role: str, content: str,
        branch: str | None = None, intent_scores: dict | None = None,
        draft: dict | None = None, metadata: dict | None = None,
    ) -> int:
        """保存单条消息到 MySQL

        Args:
            conversation_id: 对话 ID
            role: user / agent
            content: 消息文本
            branch: 当前分支（如 planner）
            intent_scores: 意图分数
            draft: 行程草案
            metadata: 其他元数据（quote, need_human 等）

        Returns:
            插入的行 ID
        """
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    INSERT INTO chat_messages
                        (conversation_id, role, content, branch, intent_scores, draft, metadata)
                    VALUES (:cid, :role, :content, :branch, :scores, :draft, :meta)
                """),
                {
                    "cid": conversation_id,
                    "role": role,
                    "content": content,
                    "branch": branch,
                    "scores": json.dumps(intent_scores, ensure_ascii=False) if intent_scores else None,
                    "draft": json.dumps(draft, ensure_ascii=False) if draft else None,
                    "meta": json.dumps(metadata, ensure_ascii=False) if metadata else None,
                },
            )
            # 同步更新 conversations.updated_at，保证侧边栏时间准确
            await conn.execute(
                text("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
            return result.lastrowid

    async def get_messages(
        self, conversation_id: str, limit: int = 50, since: str | None = None,
    ) -> list[dict]:
        """获取对话消息列表（按时间正序）

        Args:
            conversation_id: 对话 ID
            limit: 最多返回条数
            since: ISO 时间字符串，只返回此时间之后的消息

        Returns:
            [{"id":1, "role":"user", "content":"...", "branch":"planner",
              "intent_scores":{...}, "created_at":"..."}, ...]
        """
        engine = get_engine()
        params = {"cid": conversation_id, "limit": limit}

        query = """
            SELECT id, role, content, branch, intent_scores, draft, metadata, created_at
            FROM chat_messages
            WHERE conversation_id = :cid
        """
        if since:
            query += " AND created_at > :since"
            params["since"] = since

        query += " ORDER BY id ASC LIMIT :limit"

        async with engine.begin() as conn:
            result = await conn.execute(text(query), params)
            rows = result.mappings().all()

        messages = []
        for r in rows:
            msg = {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "branch": r["branch"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            }
            if r["intent_scores"]:
                try:
                    msg["intent_scores"] = json.loads(r["intent_scores"]) if isinstance(r["intent_scores"], str) else r["intent_scores"]
                except (json.JSONDecodeError, TypeError):
                    pass
            if r["draft"]:
                try:
                    msg["draft"] = json.loads(r["draft"]) if isinstance(r["draft"], str) else r["draft"]
                except (json.JSONDecodeError, TypeError):
                    pass
            if r["metadata"]:
                try:
                    msg["metadata"] = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]
                except (json.JSONDecodeError, TypeError):
                    pass
            messages.append(msg)

        return messages

    async def get_message_count(self, conversation_id: str) -> int:
        """获取对话消息总数"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) as cnt FROM chat_messages WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
            row = result.mappings().first()
            return row["cnt"] if row else 0

    async def delete_expired_messages(self, before_days: int = 7) -> int:
        """清理过期消息（超过 before_days 天）"""
        engine = get_engine()
        cutoff = datetime.now(timezone.utc) - timedelta(days=before_days)
        async with engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM chat_messages WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            deleted = result.rowcount
            if deleted:
                logger.info(f"Cleaned up {deleted} expired messages (>{before_days}d)")
            return deleted

    # =========================================================================
    # 短期记忆——上下文摘要
    # =========================================================================

    async def save_summary(
        self, conversation_id: str, summary: str,
        from_round: int, to_round: int, token_count: int = 0,
    ) -> None:
        """保存对话摘要（UPSERT）"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO chat_summaries
                        (conversation_id, summary, from_round, to_round, token_count)
                    VALUES (:cid, :summary, :fr, :tr, :tc)
                    ON DUPLICATE KEY UPDATE
                        summary = VALUES(summary),
                        from_round = VALUES(from_round),
                        to_round = VALUES(to_round),
                        token_count = VALUES(token_count)
                """),
                {
                    "cid": conversation_id,
                    "summary": summary,
                    "fr": from_round,
                    "tr": to_round,
                    "tc": token_count,
                },
            )

    async def get_summary(self, conversation_id: str) -> dict | None:
        """获取对话摘要"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM chat_summaries WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return {
                "summary": row["summary"],
                "from_round": row["from_round"],
                "to_round": row["to_round"],
                "token_count": row["token_count"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            }

    # =========================================================================
    # 短期记忆——上下文窗口（Token 估算 + 摘要触发）
    # =========================================================================

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗估 token 数：中文 ~1.5 字/token，英文 ~4 字/token"""
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        other = len(text) - chinese
        return int(chinese / 1.5) + int(other / 4) + 4  # +4 消息角色开销

    @staticmethod
    def estimate_messages_tokens(messages: list[dict]) -> int:
        """估算消息列表总 token 数"""
        total = 0
        for m in messages:
            content = m.get("content", "")
            total += MemoryManager.estimate_tokens(content)
        return total

    def should_summarize(self, messages: list[dict]) -> bool:
        """检查是否需要触发摘要（超过上下文窗口 70%）"""
        window = int(os.getenv("CONTEXT_WINDOW_TOKENS", "32768"))
        threshold = float(os.getenv("CONTEXT_SUMMARY_THRESHOLD", "0.7"))
        return self.estimate_messages_tokens(messages) > threshold * window

    async def generate_summary(self, messages: list[dict]) -> str:
        """调用 LLM 生成对话摘要"""
        from services.llm import get_router_llm
        from prompts import load_prompt

        llm = get_router_llm()
        prompt = load_prompt("summary.txt")

        msgs_text = "\n".join(
            f"[{m.get('role', '?')}] {m.get('content', '')[:500]}"
            for m in messages
        )

        response = await llm.ainvoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"请为以下对话生成摘要：\n\n{msgs_text}"},
        ])
        return response.content

    async def trim_context(
        self, conversation_id: str, messages: list[dict],
    ) -> list[dict]:
        """裁剪上下文：如果超过阈值，生成摘要并保留最近 N 轮

        Args:
            conversation_id: 对话 ID
            messages: 完整消息列表（按时间正序）

        Returns:
            裁剪后的消息列表（包含摘要 system message）
        """
        if not self.should_summarize(messages):
            return messages

        keep = int(os.getenv("CONTEXT_KEEP_RECENT_ROUNDS", "10"))
        # 保留最近 N 轮（每轮 = user + agent 两条消息）
        recent_count = keep * 2
        older = messages[:-recent_count] if len(messages) > recent_count else []
        recent = messages[-recent_count:] if len(messages) > recent_count else messages

        if not older:
            return messages

        # 生成摘要
        summary = await self.generate_summary(older)

        # 保存到 MySQL
        from_round = 1
        to_round = len(older) // 2
        await self.save_summary(
            conversation_id, summary,
            from_round=from_round, to_round=to_round,
            token_count=self.estimate_messages_tokens(older),
        )

        # 也缓存到 Redis
        try:
            from services.redis import cache_chat_summary
            await cache_chat_summary(conversation_id, summary)
        except Exception:
            pass

        logger.info(
            f"Context trimmed: {len(older)} older messages → summary ({len(summary)} chars), "
            f"keeping {len(recent)} recent"
        )

        # 构建优化后的上下文
        result = [{
            "role": "system",
            "content": f"[对话历史摘要]\n{summary}\n\n---\n请基于以上摘要和最新对话继续服务。",
        }]
        result.extend(recent)
        return result

    # =========================================================================
    # 中期记忆——LLM 偏好提取
    # =========================================================================

    async def extract_preferences(
        self, user_id: str, conversation_id: str, messages: list[dict],
    ) -> dict | None:
        """使用 LLM 从对话中提取用户旅行偏好

        Args:
            user_id: 用户 ID
            conversation_id: 来源对话 ID
            messages: 对话消息列表

        Returns:
            提取的偏好 dict 或 None（提取失败时）
        """
        from services.llm import get_router_llm
        from prompts import load_prompt

        llm = get_router_llm()

        # 只取用户消息和 agent 消息的内容
        msgs_text = "\n".join(
            f"[{m.get('role', '?')}] {m.get('content', '')[:300]}"
            for m in messages[-30:]  # 最近 30 条足够
        )

        prompt = load_prompt("preference_extract.txt")

        try:
            # 使用 structured output 解析为 Pydantic
            from pydantic import BaseModel, Field
            from typing import Optional as Opt

            class PrefExtract(BaseModel):
                preferred_destinations: list[str] = Field(default_factory=list)
                budget_range: Opt[str] = None
                travel_style: Opt[str] = None
                interests: list[str] = Field(default_factory=list)
                travel_companion: Opt[str] = None
                special_needs: Opt[str] = None
                preferred_seasons: Opt[str] = None
                confidence: float = 0.5

            structured_llm = llm.with_structured_output(PrefExtract)
            result: PrefExtract = await structured_llm.ainvoke([
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"对话历史：\n\n{msgs_text}"},
            ])

            prefs = result.model_dump(exclude_none=True)
            prefs["user_id"] = user_id
            prefs["source_conversation_id"] = conversation_id

            logger.info(
                f"Preferences extracted for user {user_id}: "
                f"destinations={result.preferred_destinations}, "
                f"confidence={result.confidence:.2f}"
            )
            return prefs

        except Exception as e:
            logger.warning(f"Preference extraction failed: {e}")
            return None

    async def save_preferences(self, prefs: dict, ttl_days: int = 60) -> int | None:
        """保存提取的偏好到 MySQL（upsert 逻辑：去重合并）

        Returns:
            插入的 ID 或 None
        """
        if not prefs:
            return None

        expire_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    INSERT INTO user_preferences
                        (user_id, preferred_destinations, budget_range, travel_style,
                         interests, travel_companion, special_needs, preferred_seasons,
                         language_pref, source_conversation_id, confidence, expire_at)
                    VALUES (:uid, :dest, :budget, :style, :interests, :companion,
                            :needs, :seasons, :lang, :src, :conf, :exp)
                """),
                {
                    "uid": prefs["user_id"],
                    "dest": json.dumps(prefs.get("preferred_destinations", []), ensure_ascii=False),
                    "budget": prefs.get("budget_range"),
                    "style": prefs.get("travel_style"),
                    "interests": json.dumps(prefs.get("interests", []), ensure_ascii=False),
                    "companion": prefs.get("travel_companion"),
                    "needs": prefs.get("special_needs"),
                    "seasons": prefs.get("preferred_seasons"),
                    "lang": prefs.get("language_pref", "zh"),
                    "src": prefs.get("source_conversation_id"),
                    "conf": prefs.get("confidence", 0.5),
                    "exp": expire_at,
                },
            )
            return result.lastrowid

    async def get_active_preferences(self, user_id: str) -> list[dict]:
        """获取用户未过期的中期偏好快照"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM user_preferences
                    WHERE user_id = :uid
                      AND (expire_at IS NULL OR expire_at > NOW())
                    ORDER BY created_at DESC
                    LIMIT 10
                """),
                {"uid": user_id},
            )
            rows = result.mappings().all()

        snapshots = []
        for r in rows:
            s = {
                "id": r["id"],
                "user_id": r["user_id"],
                "source_conversation_id": r["source_conversation_id"],
                "budget_range": r["budget_range"],
                "travel_style": r["travel_style"],
                "travel_companion": r["travel_companion"],
                "special_needs": r["special_needs"],
                "preferred_seasons": r["preferred_seasons"],
                "language_pref": r["language_pref"],
                "confidence": float(r["confidence"]) if r["confidence"] else 0.5,
                "is_promoted": False,
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "expire_at": r["expire_at"].isoformat() if r["expire_at"] else "",
            }
            if r["preferred_destinations"]:
                try:
                    s["preferred_destinations"] = json.loads(r["preferred_destinations"]) if isinstance(r["preferred_destinations"], str) else r["preferred_destinations"]
                except (json.JSONDecodeError, TypeError):
                    s["preferred_destinations"] = []
            else:
                s["preferred_destinations"] = []
            if r["interests"]:
                try:
                    s["interests"] = json.loads(r["interests"]) if isinstance(r["interests"], str) else r["interests"]
                except (json.JSONDecodeError, TypeError):
                    s["interests"] = []
            else:
                s["interests"] = []
            snapshots.append(s)

        return snapshots

    async def delete_expired_preferences(self) -> int:
        """清理过期的偏好快照"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM user_preferences WHERE expire_at < NOW()"),
            )
            deleted = result.rowcount
            if deleted:
                logger.info(f"Cleaned up {deleted} expired preference snapshots")
            return deleted

    # =========================================================================
    # 长期记忆——用户画像 CRUD
    # =========================================================================

    async def get_profile(self, user_id: str) -> dict | None:
        """获取用户画像"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_profile(row)

    async def ensure_profile(self, user_id: str, username: str) -> dict:
        """确保用户画像存在（不存在则创建）"""
        profile = await self.get_profile(user_id)
        if profile:
            return profile

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO user_profiles (user_id, display_name, preferred_language, source)
                    VALUES (:uid, :name, 'zh', 'manual')
                    ON DUPLICATE KEY UPDATE last_active_at = NOW()
                """),
                {"uid": user_id, "name": username},
            )

        return {
            "user_id": user_id,
            "username": username,
            "display_name": username,
            "preferred_language": "zh",
            "preferred_destinations": [],
            "interests": [],
            "special_needs": [],
            "preferred_seasons": [],
            "suggested_fields": None,
            "source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_active_at": datetime.now(timezone.utc).isoformat(),
        }

    async def update_profile(self, user_id: str, updates: dict) -> bool:
        """更新用户画像字段

        Args:
            user_id: 用户 ID
            updates: 要更新的字段 dict（键为列名）

        Returns:
            是否成功
        """
        if not updates:
            return True

        # 过滤出 user_profiles 表中实际存在的列
        valid_columns = {
            "display_name", "avatar_url", "email", "phone",
            "nationality", "passport_country", "preferred_language",
            "preferred_destinations", "budget_range", "travel_style",
            "interests", "travel_companion", "special_needs",
            "preferred_seasons", "suggested_fields", "source",
            "last_active_at",
        }

        set_clauses = []
        params = {"uid": user_id}

        for key, value in updates.items():
            if key not in valid_columns:
                continue
            if key in ("preferred_destinations", "interests", "special_needs",
                        "preferred_seasons", "suggested_fields", "budget_range"):
                set_clauses.append(f"{key} = :{key}")
                params[key] = json.dumps(value, ensure_ascii=False) if value is not None else None
            else:
                set_clauses.append(f"{key} = :{key}")
                params[key] = value

        if not set_clauses:
            return True

        set_clauses.append("updated_at = NOW()")

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(f"UPDATE user_profiles SET {', '.join(set_clauses)} WHERE user_id = :uid"),
                params,
            )

        return True

    async def merge_suggestions(self, user_id: str) -> dict | None:
        """将 suggested_fields 合并到画像主字段（采纳 LLM 建议）

        Returns:
            合并后的画像 dict 或 None
        """
        profile = await self.get_profile(user_id)
        if not profile:
            return None

        suggested = profile.get("suggested_fields")
        if not suggested or not isinstance(suggested, dict):
            return profile

        # 合并：建议值覆盖现有值（仅覆盖非空建议）
        list_fields = ("preferred_destinations", "interests", "special_needs", "preferred_seasons")
        scalar_fields = ("budget_range", "travel_style", "travel_companion")

        for field in list_fields:
            if field in suggested and suggested[field]:
                current = profile.get(field, []) or []
                new_vals = suggested[field] if isinstance(suggested[field], list) else [suggested[field]]
                merged = list(set(current + new_vals))
                profile[field] = merged

        for field in scalar_fields:
            if field in suggested and suggested[field]:
                profile[field] = suggested[field]

        # 清除 suggested_fields
        await self.update_profile(user_id, {
            **profile,
            "suggested_fields": None,
            "source": "llm_extract",
        })

        # 重新加载确保数据一致
        return await self.get_profile(user_id)

    async def reject_suggestions(self, user_id: str) -> bool:
        """拒绝 LLM 建议（清空 suggested_fields）"""
        return await self.update_profile(user_id, {"suggested_fields": None})

    async def update_last_active(self, user_id: str) -> None:
        """更新用户最后活跃时间"""
        try:
            await self.update_profile(user_id, {"last_active_at": datetime.now(timezone.utc)})
        except Exception:
            pass

    # =========================================================================
    # 销售 Pipeline——跟踪用户购买漏斗（Phase 20）
    # =========================================================================

    async def upsert_pipeline(self, user_id: str, data: dict) -> None:
        """创建或更新销售 Pipeline 记录（每个 user 最多一条 active）

        若已有 active pipeline，更新；否则插入新记录。

        Args:
            user_id: 用户 ID
            data: pipeline 数据 {stage, draft_id, destination, days, pax, budget, ...}
        """
        engine = get_engine()
        async with engine.begin() as conn:
            # 检查是否已有 active pipeline
            result = await conn.execute(
                text("SELECT id, followup_count FROM sales_pipeline WHERE user_id = :uid AND status = 'active' LIMIT 1"),
                {"uid": user_id},
            )
            existing = result.mappings().first()

            if existing:
                # 更新已有记录
                set_clauses = ["updated_at = NOW()"]
                params = {"id": existing["id"]}
                for key in ("stage", "draft_id", "destination", "days", "pax", "budget",
                            "discount_offered", "discount_detail"):
                    if key in data:
                        set_clauses.append(f"{key} = :{key}")
                        params[key] = data[key]
                if set_clauses:
                    await conn.execute(
                        text(f"UPDATE sales_pipeline SET {', '.join(set_clauses)} WHERE id = :id"),
                        params,
                    )
            else:
                # 插入新记录
                await conn.execute(
                    text("""
                        INSERT INTO sales_pipeline
                            (user_id, draft_id, destination, days, pax, budget, stage, status)
                        VALUES (:uid, :draft_id, :dest, :days, :pax, :budget, :stage, 'active')
                    """),
                    {
                        "uid": user_id,
                        "draft_id": data.get("draft_id", ""),
                        "dest": data.get("destination", ""),
                        "days": data.get("days"),
                        "pax": data.get("pax"),
                        "budget": data.get("budget", ""),
                        "stage": data.get("stage", "lead"),
                    },
                )

    async def get_active_pipeline(self, user_id: str) -> dict | None:
        """获取用户当前 active 的 pipeline（最多 1 条）

        Returns:
            pipeline dict 或 None
        """
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM sales_pipeline
                    WHERE user_id = :uid AND status = 'active'
                    ORDER BY updated_at DESC LIMIT 1
                """),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_pipeline(row)

    async def update_pipeline_stage(self, user_id: str, stage: str) -> None:
        """更新 active pipeline 的阶段（同时递增 followup_count 如果从外部触发）

        Args:
            user_id: 用户 ID
            stage: 新阶段
        """
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE sales_pipeline SET stage = :stage, updated_at = NOW()
                    WHERE user_id = :uid AND status = 'active'
                """),
                {"stage": stage, "uid": user_id},
            )

    async def increment_followup(self, user_id: str) -> int:
        """递增跟进计数 + 更新时间

        Returns:
            当前跟进次数
        """
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE sales_pipeline
                    SET followup_count = followup_count + 1, updated_at = NOW()
                    WHERE user_id = :uid AND status = 'active'
                """),
                {"uid": user_id},
            )
            result = await conn.execute(
                text("SELECT followup_count FROM sales_pipeline WHERE user_id = :uid AND status = 'active'"),
                {"uid": user_id},
            )
            row = result.mappings().first()
            return row["followup_count"] if row else 0

    async def mark_pipeline_won(self, user_id: str) -> None:
        """标记 pipeline 为成交"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE sales_pipeline
                    SET status = 'won', stage = 'won', converted_at = NOW(), updated_at = NOW()
                    WHERE user_id = :uid AND status = 'active'
                """),
                {"uid": user_id},
            )

    async def mark_pipeline_lost(self, user_id: str) -> None:
        """标记 pipeline 为流失"""
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE sales_pipeline
                    SET status = 'lost', stage = 'lost', updated_at = NOW()
                    WHERE user_id = :uid AND status = 'active'
                """),
                {"uid": user_id},
            )

    def _row_to_pipeline(self, row) -> dict:
        """将 SQL 行转为 pipeline dict"""
        pipeline = {
            "id": row["id"],
            "user_id": row["user_id"],
            "draft_id": row["draft_id"],
            "destination": row["destination"],
            "days": row["days"],
            "pax": row["pax"],
            "budget": row["budget"],
            "stage": row["stage"],
            "followup_count": row["followup_count"],
            "discount_offered": bool(row["discount_offered"]),
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
            "converted_at": row["converted_at"].isoformat() if row["converted_at"] else None,
        }
        discount = row["discount_detail"]
        if discount:
            try:
                pipeline["discount_detail"] = json.loads(discount) if isinstance(discount, str) else discount
            except (json.JSONDecodeError, TypeError):
                pipeline["discount_detail"] = None
        else:
            pipeline["discount_detail"] = None
        return pipeline

    # =========================================================================
    # 订单——跟踪用户订单生命周期（Phase 21）
    # =========================================================================

    async def create_order(self, user_id: str, data: dict) -> dict:
        """创建新订单

        Args:
            user_id: 用户 ID
            data: {order_id, draft_id, destination, days, pax, trip_start,
                   trip_end, total_amount, currency, items, status}

        Returns:
            创建的订单 dict
        """
        import json as _json
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO orders
                        (order_id, user_id, draft_id, status, destination, days, pax,
                         trip_start, trip_end, total_amount, currency, items)
                    VALUES (:oid, :uid, :did, :status, :dest, :days, :pax,
                            :tstart, :tend, :amount, :currency, :items)
                """),
                {
                    "oid": data.get("order_id", ""),
                    "uid": user_id,
                    "did": data.get("draft_id", ""),
                    "status": data.get("status", "pending_confirmation"),
                    "dest": data.get("destination", ""),
                    "days": data.get("days"),
                    "pax": data.get("pax"),
                    "tstart": data.get("trip_start"),
                    "tend": data.get("trip_end"),
                    "amount": data.get("total_amount", ""),
                    "currency": data.get("currency", "¥"),
                    "items": _json.dumps(data.get("items", []), ensure_ascii=False),
                },
            )
        return await self.get_order(data.get("order_id", ""))

    async def get_order(self, order_id: str) -> dict | None:
        """按 order_id 查询订单

        Returns:
            order dict 或 None
        """
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM orders WHERE order_id = :oid LIMIT 1"),
                {"oid": order_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_order(row)

    async def get_active_order(self, user_id: str) -> dict | None:
        """获取用户当前活跃订单（status 不是 completed/cancelled）

        Returns:
            活跃的 order dict 或 None
        """
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM orders
                    WHERE user_id = :uid AND status NOT IN ('completed', 'cancelled')
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_order(row)

    async def list_orders(self, user_id: str, limit: int = 10) -> list[dict]:
        """列出用户订单（按创建时间降序）

        Returns:
            订单列表
        """
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM orders
                    WHERE user_id = :uid
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "lim": limit},
            )
            rows = result.mappings().all()
            return [self._row_to_order(r) for r in rows]

    async def update_order_status(self, order_id: str, status: str) -> None:
        """更新订单状态

        Args:
            order_id: 订单号
            status: 新状态
        """
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE orders SET status = :status, updated_at = NOW()
                    WHERE order_id = :oid
                """),
                {"status": status, "oid": order_id},
            )

    def _row_to_order(self, row) -> dict:
        """将 SQL 行转为 order dict"""
        import json as _json
        order = {
            "id": row["id"],
            "order_id": row["order_id"],
            "user_id": row["user_id"],
            "draft_id": row["draft_id"],
            "status": row["status"],
            "destination": row["destination"],
            "days": row["days"],
            "pax": row["pax"],
            "trip_start": row["trip_start"].isoformat() if row["trip_start"] else "",
            "trip_end": row["trip_end"].isoformat() if row["trip_end"] else "",
            "total_amount": row["total_amount"],
            "currency": row["currency"],
            "paid_at": row["paid_at"].isoformat() if row["paid_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
        }
        items = row["items"]
        if items:
            try:
                order["items"] = _json.loads(items) if isinstance(items, str) else items
            except (_json.JSONDecodeError, TypeError):
                order["items"] = []
        else:
            order["items"] = []
        return order

    # =========================================================================
    # 工单——跟踪售后处理（Phase 21）
    # =========================================================================

    async def create_ticket(self, user_id: str, data: dict) -> dict:
        """创建新工单

        Args:
            user_id: 用户 ID
            data: {ticket_id, order_id, type, priority, description}

        Returns:
            创建的工单 dict
        """
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO tickets
                        (ticket_id, user_id, order_id, type, priority, status, description)
                    VALUES (:tid, :uid, :oid, :type, :priority, 'open', :desc)
                """),
                {
                    "tid": data.get("ticket_id", ""),
                    "uid": user_id,
                    "oid": data.get("order_id", ""),
                    "type": data.get("type", "inquiry"),
                    "priority": data.get("priority", "normal"),
                    "desc": data.get("description", ""),
                },
            )
        return await self.get_ticket(data.get("ticket_id", ""))

    async def get_ticket(self, ticket_id: str) -> dict | None:
        """按 ticket_id 查询工单

        Returns:
            ticket dict 或 None
        """
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM tickets WHERE ticket_id = :tid LIMIT 1"),
                {"tid": ticket_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_ticket(row)

    async def list_tickets(self, user_id: str) -> list[dict]:
        """列出用户工单（按创建时间降序）"""
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM tickets
                    WHERE user_id = :uid
                    ORDER BY created_at DESC
                    LIMIT 20
                """),
                {"uid": user_id},
            )
            rows = result.mappings().all()
            return [self._row_to_ticket(r) for r in rows]

    async def update_ticket(self, ticket_id: str, data: dict) -> None:
        """更新工单

        Args:
            ticket_id: 工单号
            data: {status, resolution, resolved_at, ...}
        """
        engine = get_engine()
        async with engine.begin() as conn:
            set_clauses = ["updated_at = NOW()"]
            params = {"tid": ticket_id}
            for key in ("status", "resolution", "resolved_at"):
                if key in data:
                    set_clauses.append(f"{key} = :{key}")
                    params[key] = data[key]
            if set_clauses:
                await conn.execute(
                    text(f"UPDATE tickets SET {', '.join(set_clauses)} WHERE ticket_id = :tid"),
                    params,
                )

    def _row_to_ticket(self, row) -> dict:
        """将 SQL 行转为 ticket dict"""
        return {
            "id": row["id"],
            "ticket_id": row["ticket_id"],
            "user_id": row["user_id"],
            "order_id": row["order_id"],
            "type": row["type"],
            "priority": row["priority"],
            "status": row["status"],
            "description": row["description"],
            "resolution": row["resolution"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
            "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        }

    def _row_to_profile(self, row) -> dict:
        """将 SQL 查询行转为 profile dict"""
        profile = {
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "avatar_url": row["avatar_url"],
            "email": row["email"],
            "phone": row["phone"],
            "nationality": row["nationality"],
            "passport_country": row["passport_country"],
            "preferred_language": row["preferred_language"] or "zh",
            "budget_range": None,
            "travel_style": row["travel_style"],
            "travel_companion": row["travel_companion"],
            "source": row["source"] or "manual",
            "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
            "last_active_at": row["last_active_at"].isoformat() if row["last_active_at"] else "",
        }

        # 解析 JSON 字段
        for json_field in ("preferred_destinations", "interests", "special_needs", "preferred_seasons"):
            val = row.get(json_field)
            if val:
                try:
                    profile[json_field] = json.loads(val) if isinstance(val, str) else (val if val else [])
                except (json.JSONDecodeError, TypeError):
                    profile[json_field] = []
            else:
                profile[json_field] = []

        # 解析 budget_range JSON → dict
        budget_val = row.get("budget_range")
        if budget_val:
            try:
                profile["budget_range"] = json.loads(budget_val) if isinstance(budget_val, str) else budget_val
            except (json.JSONDecodeError, TypeError):
                profile["budget_range"] = None

        # 解析 suggested_fields
        sug = row.get("suggested_fields")
        if sug:
            try:
                profile["suggested_fields"] = json.loads(sug) if isinstance(sug, str) else sug
            except (json.JSONDecodeError, TypeError):
                profile["suggested_fields"] = None
        else:
            profile["suggested_fields"] = None

        return profile
