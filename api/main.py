"""FastAPI 入口——入境定制游多 Agent 系统

启动方式：
    Docker:  docker-compose up --build
    本地:    python main.py

服务依赖：
    - MySQL 8.0（会话持久化 + LangGraph Checkpoint + 用户/对话）
    - Redis 7（会话缓存 + 摘要缓存）
    - Milvus 单机（向量检索）
    - 阿里百炼（LLM + Embedding）
"""

import os
import sys
import json
import time
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# 启动时加载 .env
load_dotenv()

# 日志
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "info").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from api.schemas import (
    ChatRequest, ChatResponse, TripDraftResponse,
    ConversationItem, CreateConversationRequest, CreateConversationResponse,
    UserProfileResponse, UserProfileUpdateRequest,
    PendingUpdateResponse, PreferenceSnapshotResponse,
    ConversationMessagesResponse, ChatMessageItem,
    BudgetRange,
)
from api.dependencies import get_current_user
from graph.builder import build_graph


# =============================================================================
# 生命周期管理
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的初始化与清理"""
    # ---- 启动 ----
    logger.info("=" * 50)
    logger.info("入境定制游 AI Agent 启动中...")
    logger.info("=" * 50)

    # MySQL
    try:
        from services.mysql import init_mysql
        await init_mysql()
    except Exception as e:
        logger.warning(f"MySQL 初始化失败（会话将使用内存）: {e}")

    # Redis
    try:
        from services.redis import init_redis
        await init_redis()
    except Exception as e:
        logger.warning(f"Redis 初始化失败（缓存将不可用）: {e}")

    # Milvus（同步初始化，在线程池中运行）
    try:
        import asyncio
        from services.vector_store import init_milvus
        await asyncio.to_thread(init_milvus)
    except Exception as e:
        logger.warning(f"Milvus 初始化失败（RAG 将回退到关键词匹配）: {e}")

    # MySQL 业务表初始化
    try:
        from services.mysql import get_engine
        engine = get_engine()
        from sqlalchemy import text

        # LangGraph Checkpoint 表
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id VARCHAR(255) NOT NULL,
                    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                    checkpoint_id VARCHAR(255) NOT NULL,
                    parent_checkpoint_id VARCHAR(255),
                    type VARCHAR(255),
                    checkpoint LONGBLOB NOT NULL,
                    metadata LONGBLOB,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id VARCHAR(255) NOT NULL,
                    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                    checkpoint_id VARCHAR(255) NOT NULL,
                    task_id VARCHAR(255) NOT NULL,
                    idx INT NOT NULL,
                    channel VARCHAR(255) NOT NULL,
                    type VARCHAR(255),
                    value LONGBLOB,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))

        # 用户 + 对话表
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     VARCHAR(64)  PRIMARY KEY COMMENT '用户唯一标识',
                    username    VARCHAR(50)  NOT NULL UNIQUE COMMENT '用户名',
                    password    VARCHAR(255) NOT NULL COMMENT 'bcrypt 密码哈希',
                    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_username (username)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id VARCHAR(64)  PRIMARY KEY COMMENT '对话唯一标识',
                    user_id         VARCHAR(64)  NOT NULL COMMENT '所属用户',
                    title           VARCHAR(200) NOT NULL DEFAULT '新对话',
                    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    INDEX idx_user (user_id),
                    INDEX idx_updated (updated_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))

        # 记忆系统表
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(64) NOT NULL,
                    role            VARCHAR(16) NOT NULL,
                    content         TEXT        NOT NULL,
                    branch          VARCHAR(32),
                    intent_scores   JSON,
                    draft           JSON,
                    metadata        JSON,
                    created_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_conv_time (conversation_id, created_at),
                    INDEX idx_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_summaries (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(64) NOT NULL,
                    summary         TEXT        NOT NULL,
                    from_round      INT         NOT NULL,
                    to_round        INT         NOT NULL,
                    token_count     INT,
                    created_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_conv (conversation_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id             VARCHAR(64) NOT NULL,
                    preferred_destinations JSON,
                    budget_range        VARCHAR(32),
                    travel_style        VARCHAR(20),
                    interests           JSON,
                    travel_companion    VARCHAR(20),
                    special_needs       VARCHAR(255),
                    preferred_seasons   VARCHAR(128),
                    language_pref       VARCHAR(8)  DEFAULT 'zh',
                    source_conversation_id VARCHAR(64),
                    confidence          FLOAT       DEFAULT 0.5,
                    expire_at           TIMESTAMP,
                    created_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_user (user_id),
                    INDEX idx_expire (expire_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id             VARCHAR(64) PRIMARY KEY,
                    display_name        VARCHAR(64),
                    avatar_url          VARCHAR(255),
                    email               VARCHAR(128),
                    phone               VARCHAR(32),
                    nationality         VARCHAR(64),
                    passport_country    VARCHAR(64),
                    preferred_language  VARCHAR(8)  DEFAULT 'zh',
                    preferred_destinations JSON,
                    budget_range         VARCHAR(32),
                    travel_style         VARCHAR(20),
                    interests            JSON,
                    travel_companion     VARCHAR(20),
                    special_needs        VARCHAR(255),
                    preferred_seasons    VARCHAR(128),
                    suggested_fields     JSON,
                    source              VARCHAR(16) DEFAULT 'manual',
                    created_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    last_active_at      TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))

        logger.info("MySQL business tables verified")
    except Exception as e:
        logger.warning(f"业务表初始化跳过: {e}")

    logger.info("应用启动完成 ✓")
    logger.info(f"  LLM Router:  {os.getenv('ROUTER_MODEL', 'qwen-plus')}")
    logger.info(f"  LLM Agent:   {os.getenv('AGENT_MODEL', 'qwen3-max')}")
    logger.info(f"  Embedding:   {os.getenv('EMBEDDING_MODEL', 'text-embedding-v4')}")
    logger.info(f"  Checkpoint:  {os.getenv('CHECKPOINT_BACKEND', 'mysql')}")

    # 后台定期清理过期数据（每小时一次）
    async def _periodic_cleanup():
        while True:
            await asyncio.sleep(3600)
            try:
                from services.memory import MemoryManager
                mm = MemoryManager()
                deleted_msgs = await mm.delete_expired_messages(before_days=7)
                deleted_prefs = await mm.delete_expired_preferences()
                if deleted_msgs or deleted_prefs:
                    logger.info(
                        f"Periodic cleanup: {deleted_msgs} messages, {deleted_prefs} preferences"
                    )
            except Exception as e:
                logger.debug(f"Periodic cleanup skipped: {e}")

    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield

    # ---- 关闭 ----
    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except asyncio.CancelledError:
        pass

    # ---- 关闭 ----
    logger.info("应用关闭中...")
    try:
        from services.mysql import close_mysql
        await close_mysql()
    except Exception:
        pass
    try:
        from services.redis import close_redis
        await close_redis()
    except Exception:
        pass
    try:
        from services.vector_store import close_milvus
        close_milvus()
    except Exception:
        pass
    logger.info("应用已关闭")


# =============================================================================
# FastAPI 应用
# =============================================================================

app = FastAPI(
    title="入境定制游 AI Agent",
    description="基于 LangGraph 的多 Agent 旅游规划系统（阿里百炼 + Milvus + MySQL + Redis）",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局图实例（单例，通过 thread_id 隔离会话）
_graph = build_graph()

# 注册认证路由
from api.auth import router as auth_router
app.include_router(auth_router)


# =============================================================================
# 静态文件服务
# =============================================================================

_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# =============================================================================
# 路由
# =============================================================================


@app.get("/")
async def root():
    """返回前端页面"""
    index_path = os.path.join(_static_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": "前端页面未找到，请访问 /docs 查看 API 文档", "version": "0.3.0"}


@app.get("/health")
async def health_check():
    """健康检查——返回各组件连接状态"""
    status = {
        "status": "ok",
        "version": "0.3.0",
        "components": {
            "api": "ok",
        }
    }

    # MySQL
    try:
        from services.mysql import get_engine
        engine = get_engine()
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        status["components"]["mysql"] = "ok"
    except Exception:
        status["components"]["mysql"] = "unavailable"

    # Redis
    try:
        from services.redis import get_redis
        r = get_redis()
        await r.ping()
        status["components"]["redis"] = "ok"
    except Exception:
        status["components"]["redis"] = "unavailable"

    # Milvus
    try:
        from services.vector_store import get_collection_stats
        stats = get_collection_stats()
        status["components"]["milvus"] = {"status": "ok", **stats}
    except Exception:
        status["components"]["milvus"] = "unavailable"

    # 综合状态
    if any(
        v != "ok" and not isinstance(v, dict)
        for k, v in status["components"].items()
    ):
        status["status"] = "degraded"

    return status


# =============================================================================
# 对话管理（需认证）
# =============================================================================


@app.get("/conversations", response_model=list[ConversationItem])
async def list_conversations(user: dict = Depends(get_current_user)):
    """获取当前用户的所有对话，按更新时间倒序"""
    from services.user_store import UserStore
    store = UserStore()
    return await store.list_conversations(user["user_id"])


@app.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    req: CreateConversationRequest,
    user: dict = Depends(get_current_user),
):
    """新建对话"""
    from services.user_store import UserStore
    store = UserStore()
    conv_id = f"conv-{uuid.uuid4().hex[:12]}"
    await store.create_conversation(conv_id, user["user_id"], req.title)
    logger.info(f"Conversation created: {conv_id} by {user['username']}")
    return CreateConversationResponse(conversation_id=conv_id, title=req.title)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: dict = Depends(get_current_user),
):
    """删除对话（仅所有者可操作）"""
    from services.user_store import UserStore
    store = UserStore()
    deleted = await store.delete_conversation(conversation_id, user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="对话不存在或无权删除")

    # 同时清理 LangGraph checkpoint
    try:
        _graph.checkpointer.delete_thread(conversation_id)
    except Exception:
        pass

    return {"ok": True}


@app.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def get_messages(
    conversation_id: str,
    user: dict = Depends(get_current_user),
):
    """获取对话历史消息（优先 Redis → MySQL → Checkpoint 回退）"""
    from services.user_store import UserStore
    store = UserStore()
    conv = await store.get_conversation(conversation_id)
    if not conv or conv["user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="对话不存在")

    from services.memory import MemoryManager
    mm = MemoryManager()
    messages = []
    summary = None

    # 1. 尝试 Redis 缓存
    try:
        from services.redis import get_cached_chat_messages, get_cached_chat_summary
        cached_msgs = await get_cached_chat_messages(conversation_id)
        if cached_msgs:
            messages = cached_msgs
        summary = await get_cached_chat_summary(conversation_id)
    except Exception:
        pass

    # 2. Redis 未命中 → MySQL
    if not messages:
        try:
            messages = await mm.get_messages(conversation_id, limit=50)
            # 预热 Redis
            if messages:
                try:
                    from services.redis import cache_chat_messages
                    await cache_chat_messages(conversation_id, messages)
                except Exception:
                    pass
        except Exception:
            pass

    # 3. 尝试从 MySQL 获取摘要
    if not summary:
        try:
            summary_info = await mm.get_summary(conversation_id)
            if summary_info:
                summary = summary_info["summary"]
        except Exception:
            pass

    # 4. 都不可用 → 回退到 LangGraph checkpoint
    if not messages:
        try:
            config = {"configurable": {"thread_id": conversation_id}}
            state = await _graph.aget_state(config)
            if state and state.values:
                checkpoint_msgs = state.values.get("messages", [])
                messages = [
                    {
                        "role": "user" if getattr(m, "type", "") == "human" else "agent",
                        "content": getattr(m, "content", ""),
                        "branch": state.values.get("current_branch", ""),
                    }
                    for m in checkpoint_msgs
                ]
        except Exception:
            pass

    # 序列化为 ChatMessageItem
    msg_items = [
        ChatMessageItem(
            role=m.get("role", "agent"),
            content=m.get("content", ""),
            branch=m.get("branch"),
            intent_scores=m.get("intent_scores"),
            created_at=m.get("created_at"),
        )
        for m in messages
    ]

    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=msg_items,
        summary=summary,
    )


# =============================================================================
# 核心对话接口（需认证）
# =============================================================================


async def _post_chat_save(
    conversation_id: str, user_id: str, user_message: str,
    reply: str, branch: str | None, intent_scores: dict | None,
    draft: dict | None, quote: str | None, need_human: bool | None,
    all_messages: list, skip_user_message: bool = False,
):
    """对话后处理：保存消息 + 上下文管理 + 偏好提取（异步，不阻塞响应）

    在每次 /chat 或 /chat/stream 完成后调用。
    当 skip_user_message=True 时跳过用户消息保存（stream 端点已在开始时预存）。
    """
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()

        # 1. 保存用户消息（如果尚未预存）
        if not skip_user_message:
            await mm.save_message(conversation_id, "user", user_message)

        # 2. 保存 Agent 回复（附带元数据）
        meta = {}
        if quote:
            meta["quote"] = quote
        if need_human is not None:
            meta["need_human"] = need_human

        await mm.save_message(
            conversation_id, "agent", reply,
            branch=branch, intent_scores=intent_scores,
            draft=draft, metadata=meta,
        )

        # 3. 更新用户最后活跃时间
        await mm.update_last_active(user_id)

        # 4. 更新 Redis 缓存
        try:
            from services.redis import cache_chat_messages
            msgs = await mm.get_messages(conversation_id, limit=50)
            if msgs:
                await cache_chat_messages(conversation_id, msgs)
        except Exception:
            pass

        # 5. 上下文窗口检查——需要摘要吗？
        try:
            from services.redis import get_cached_chat_messages
            cached = await get_cached_chat_messages(conversation_id) or []
            if mm.should_summarize(cached):
                logger.info(f"Context window threshold reached for {conversation_id}, generating summary...")
                trimmed = await mm.trim_context(conversation_id, cached)
                await cache_chat_messages(conversation_id, trimmed)
        except Exception:
            pass

        # 6. 每 5 轮提取一次偏好
        try:
            msg_count = await mm.get_message_count(conversation_id)
            if msg_count >= 10 and msg_count % 10 < 2:  # 接近每 5 轮（10条消息）
                logger.info(f"Extracting preferences for user {user_id} from {conversation_id}")
                # 获取所有消息用于提取
                all_msgs = await mm.get_messages(conversation_id, limit=30)
                prefs = await mm.extract_preferences(user_id, conversation_id, all_msgs)
                if prefs:
                    await mm.save_preferences(prefs)

                    # 同时更新画像的 suggested_fields
                    profile = await mm.get_profile(user_id)
                    if not profile:
                        from services.user_store import UserStore
                        store = UserStore()
                        user_info = await store.get_conversation(conversation_id)
                        profile = await mm.ensure_profile(user_id, user_id)

                    suggested = profile.get("suggested_fields") or {}
                    if prefs.get("preferred_destinations"):
                        current_dests = set(profile.get("preferred_destinations", []) or [])
                        new_dests = [d for d in prefs["preferred_destinations"] if d not in current_dests]
                        if new_dests:
                            suggested["preferred_destinations"] = new_dests
                    for field in ("travel_style", "travel_companion", "budget_range", "preferred_seasons"):
                        if prefs.get(field) and not profile.get(field):
                            suggested[field] = prefs[field]
                    if prefs.get("interests"):
                        current = set(profile.get("interests", []) or [])
                        new = [i for i in prefs["interests"] if i not in current]
                        if new:
                            suggested["interests"] = new

                    if suggested:
                        await mm.update_profile(user_id, {"suggested_fields": suggested})
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"Post-chat save failed (non-critical): {e}")


async def _load_chat_history(conversation_id: str) -> list:
    """从 MySQL chat_messages 加载历史消息，转为 LangChain Message 列表

    用于在 checkpoint 为空时回退加载历史上下文。
    """
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()
        msgs = await mm.get_messages(conversation_id, limit=30)
        if not msgs:
            return []

        from langchain_core.messages import HumanMessage as HM, AIMessage as AM
        result = []
        for m in msgs:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "user":
                result.append(HM(content=content))
            else:
                result.append(AM(content=content))
        return result
    except Exception:
        return []


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """核心对话接口

    接收用户消息，通过 LangGraph 多 Agent 图处理，
    返回 AI 回复及结构化业务数据。
    """
    try:
        # 🧠 加载历史消息（checkpoint 空时回退 MySQL）
        history_msgs = await _load_chat_history(req.conversation_id)

        initial_state = {
            "messages": history_msgs + [HumanMessage(content=req.message)],
            "session_id": req.conversation_id,
            "customer_id": user["user_id"],
            "channel": req.channel,
            "language": req.language,
            "force_branch": "customer_service" if req.mode == "support" else "",
        }

        result = await _graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": req.conversation_id}},
        )

        # 自动更新对话标题（取用户消息前 30 字）
        try:
            from services.user_store import UserStore
            store = UserStore()
            conv = await store.get_conversation(req.conversation_id)
            if conv and conv.get("title") == "新对话":
                title = req.message[:30].replace("\n", " ")
                await store.update_conversation_title(req.conversation_id, title)
        except Exception:
            pass

        # 行程草案
        draft = result.get("draft", {}) or {}
        draft_response = None
        if draft.get("itinerary_md"):
            draft_response = TripDraftResponse(
                version=draft.get("version", 0),
                itinerary_md=draft["itinerary_md"],
                estimated_cost=draft.get("estimated_cost"),
                weather_summary=draft.get("weather_summary"),
            )

        final_reply = result.get("final_reply", "抱歉，处理您的请求时出现了问题。")
        current_branch = result.get("current_branch")
        intent_scores = result.get("intent_scores")
        need_human = result.get("need_human", False)
        quote = result.get("quote", "")

        # 异步保存消息（不阻塞响应）
        asyncio.create_task(
            _post_chat_save(
                conversation_id=req.conversation_id,
                user_id=user["user_id"],
                user_message=req.message,
                reply=final_reply,
                branch=current_branch,
                intent_scores=intent_scores,
                draft=draft_response.model_dump() if draft_response else None,
                quote=quote,
                need_human=need_human,
                all_messages=[],
            )
        )

        return ChatResponse(
            reply=final_reply,
            current_branch=current_branch,
            draft=draft_response,
            need_human=need_human,
            intent_scores=intent_scores,
        )

    except Exception as e:
        logger.exception(f"处理请求失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"处理请求时出错：{str(e)}",
        )


# =============================================================================
# 节点中文标签（SSE 进度推送用）
# =============================================================================

NODE_LABELS: dict[str, str] = {
    "input_guard": "正在检查输入...",
    "session_context": "正在加载会话...",
    "intent_router": "正在分析意图...",
    "customer_service": "正在查询知识库...",
    "trip_planner": "正在生成行程...",
    "sales_agent": "正在计算报价...",
    "operations_agent": "正在处理运营请求...",
    "human_handoff": "正在转接人工...",
    "operations_sync": "正在同步数据...",
    "revision_loop": "正在修订行程...",
    "intent_scorer": "正在评估需求...",
}


# =============================================================================
# SSE 流式对话接口（需认证）
# =============================================================================

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)):
    """流式对话接口——SSE 实时推送图节点执行进度 + 最终结果

    相比 /chat，本端点通过 text/event-stream 在 LangGraph
    每个节点完成时发送进度事件，避免用户长时间看"思考中"。

    事件格式：
        event: node_start     → {"node": "...", "label": "正在..."}
        event: node_complete  → {"node": "..."}
        event: done           → {完整 ChatResponse}
        event: error          → {"message": "..."}
    """

    async def _event_stream():
        # 🧠 加载历史消息（checkpoint 空时回退 MySQL）
        history_msgs = await _load_chat_history(req.conversation_id)

        # 🛑 提前保存用户消息——即使 SSE 流被中断/取消，下一轮也能读取完整上下文
        #    注意：正常完成后 _post_chat_save 会再次保存同一消息（幂等，不重复）
        try:
            from services.memory import MemoryManager
            mm = MemoryManager()
            await mm.save_message(req.conversation_id, "user", req.message)
        except Exception:
            pass

        initial_state = {
            "messages": history_msgs + [HumanMessage(content=req.message)],
            "session_id": req.conversation_id,
            "customer_id": user["user_id"],
            "channel": req.channel,
            "language": req.language,
            "force_branch": "customer_service" if req.mode == "support" else "",
        }

        final_state = None

        try:
            # 自动更新对话标题
            try:
                from services.user_store import UserStore
                store = UserStore()
                conv = await store.get_conversation(req.conversation_id)
                if conv and conv.get("title") == "新对话":
                    title = req.message[:30].replace("\n", " ")
                    await store.update_conversation_title(req.conversation_id, title)
            except Exception:
                pass

            async for event in _graph.astream(
                initial_state,
                config={"configurable": {"thread_id": req.conversation_id}},
                stream_mode="updates",
            ):
                for node_name, node_output in event.items():
                    label = NODE_LABELS.get(node_name, f"正在执行 {node_name}...")
                    yield f"event: node_start\ndata: {json.dumps({'node': node_name, 'label': label}, ensure_ascii=False)}\n\n"
                    final_state = node_output
                    yield f"event: node_complete\ndata: {json.dumps({'node': node_name}, ensure_ascii=False)}\n\n"

            # 构建最终响应（正常完成）
            if final_state:
                draft = final_state.get("draft", {}) or {}
                draft_resp = None
                if draft.get("itinerary_md"):
                    draft_resp = {
                        "version": draft.get("version", 0),
                        "itinerary_md": draft["itinerary_md"],
                        "estimated_cost": draft.get("estimated_cost"),
                        "weather_summary": draft.get("weather_summary"),
                    }

                resp = {
                    "reply": final_state.get("final_reply", ""),
                    "current_branch": final_state.get("current_branch"),
                    "draft": draft_resp,
                    "need_human": final_state.get("need_human", False),
                    "intent_scores": final_state.get("intent_scores"),
                    "quote": final_state.get("quote"),
                }
                yield f"event: done\ndata: {json.dumps(resp, ensure_ascii=False)}\n\n"

                # 异步保存消息（用户消息已在流开始时预存，skip_user_message=True）
                asyncio.create_task(
                    _post_chat_save(
                        conversation_id=req.conversation_id,
                        user_id=user["user_id"],
                        user_message=req.message,
                        reply=resp["reply"],
                        branch=resp.get("current_branch"),
                        intent_scores=resp.get("intent_scores"),
                        draft=draft_resp,
                        quote=resp.get("quote"),
                        need_human=resp.get("need_human"),
                        all_messages=[],
                        skip_user_message=True,
                    )
                )
            else:
                yield f"event: error\ndata: {json.dumps({'message': '处理完成但无结果'}, ensure_ascii=False)}\n\n"

        except (GeneratorExit, asyncio.CancelledError):
            # 🛑 用户主动中断——用户消息已在流开始时预存到 MySQL
            logger.info(f"用户中断 SSE 流 (conversation={req.conversation_id})")
            raise

        except Exception as e:
            logger.exception(f"SSE 流式处理失败: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# 用户画像——长期记忆（需认证）
# =============================================================================


@app.get("/profile", response_model=UserProfileResponse)
async def get_profile(user: dict = Depends(get_current_user)):
    """获取当前用户的完整画像（含 LLM 建议）"""
    try:
        from services.redis import get_cached_user_profile, cache_user_profile
        # 1. 尝试 Redis 缓存
        cached = await get_cached_user_profile(user["user_id"])
        if cached:
            return UserProfileResponse(**cached)

        # 2. MySQL 查询
        from services.memory import MemoryManager
        mm = MemoryManager()
        profile = await mm.ensure_profile(user["user_id"], user.get("username", ""))
        profile["username"] = user.get("username", "")

        # 3. 缓存到 Redis
        await cache_user_profile(user["user_id"], profile)

        return UserProfileResponse(**profile)

    except Exception as e:
        logger.exception(f"获取画像失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取画像失败: {str(e)}")


@app.put("/profile", response_model=UserProfileResponse)
async def update_profile(
    req: UserProfileUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """更新用户画像（手动编辑或接受 LLM 建议）"""
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()

        # 确保画像存在
        await mm.ensure_profile(user["user_id"], user.get("username", ""))

        # 收集要更新的字段
        updates = {}
        for field_name, value in req.model_dump(exclude_none=True, exclude={"accept_suggestions"}).items():
            if value is not None:
                # budget_range 是 BudgetRange 模型，直接用 model_dump 后的 dict
                # memory.py 会统一序列化 JSON 字段
                updates[field_name] = value

        if updates:
            updates["source"] = "manual"
            await mm.update_profile(user["user_id"], updates)

        # 如果用户选择接受 LLM 建议
        if req.accept_suggestions:
            await mm.merge_suggestions(user["user_id"])

        # 清除 Redis 缓存
        try:
            from services.redis import invalidate_user_cache
            await invalidate_user_cache(user["user_id"])
        except Exception:
            pass

        # 返回最新画像
        profile = await mm.get_profile(user["user_id"])
        profile["username"] = user.get("username", "")
        return UserProfileResponse(**profile)

    except Exception as e:
        logger.exception(f"更新画像失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新画像失败: {str(e)}")


@app.get("/profile/suggestions", response_model=list[PendingUpdateResponse])
async def get_pending_suggestions(user: dict = Depends(get_current_user)):
    """获取 LLM 建议的待确认画像更新"""
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()
        profile = await mm.get_profile(user["user_id"])
        if not profile:
            return []

        suggested = profile.get("suggested_fields")
        if not suggested or not isinstance(suggested, dict):
            return []

        items = []
        for field, value in suggested.items():
            current = profile.get(field)
            items.append(PendingUpdateResponse(
                field=field,
                current_value=str(current)[:200] if current else None,
                suggested_value=str(value)[:200] if value else None,
                confidence=0.6,
                reason=f"LLM 从您的对话中发现新偏好",
            ))
        return items

    except Exception as e:
        logger.exception(f"获取建议失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取建议失败: {str(e)}")


@app.post("/profile/suggestions/accept")
async def accept_suggestions(user: dict = Depends(get_current_user)):
    """采纳所有 LLM 建议——合并到画像主字段"""
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()
        profile = await mm.merge_suggestions(user["user_id"])
        if not profile:
            raise HTTPException(status_code=404, detail="画像不存在")

        # 清除缓存
        try:
            from services.redis import invalidate_user_cache
            await invalidate_user_cache(user["user_id"])
        except Exception:
            pass

        profile["username"] = user.get("username", "")
        return {"ok": True, "profile": UserProfileResponse(**profile)}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"采纳建议失败: {e}")
        raise HTTPException(status_code=500, detail=f"采纳建议失败: {str(e)}")


@app.post("/profile/suggestions/reject")
async def reject_suggestions(user: dict = Depends(get_current_user)):
    """拒绝所有 LLM 建议——清空 suggested_fields"""
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()
        await mm.reject_suggestions(user["user_id"])

        try:
            from services.redis import invalidate_user_cache
            await invalidate_user_cache(user["user_id"])
        except Exception:
            pass

        return {"ok": True}
    except Exception as e:
        logger.exception(f"拒绝建议失败: {e}")
        raise HTTPException(status_code=500, detail=f"拒绝建议失败: {str(e)}")


@app.get("/preferences", response_model=list[PreferenceSnapshotResponse])
async def get_preferences(user: dict = Depends(get_current_user)):
    """获取用户的中期偏好快照（LLM 自动提取）"""
    try:
        from services.memory import MemoryManager
        mm = MemoryManager()
        snapshots = await mm.get_active_preferences(user["user_id"])

        return [
            PreferenceSnapshotResponse(
                id=s["id"],
                source_conversation_id=s["source_conversation_id"],
                preferred_destinations=s.get("preferred_destinations", []),
                budget_range=s.get("budget_range"),
                travel_style=s.get("travel_style"),
                interests=s.get("interests", []),
                travel_companion=s.get("travel_companion"),
                special_needs=s.get("special_needs"),
                preferred_seasons=s.get("preferred_seasons"),
                confidence=s.get("confidence", 0.5),
                is_promoted=s.get("is_promoted", False),
                created_at=s.get("created_at"),
                expire_at=s.get("expire_at"),
            )
            for s in snapshots
        ]
    except Exception as e:
        logger.exception(f"获取偏好失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取偏好失败: {str(e)}")


# =============================================================================
# 命令行入口（本地调试 / 测试）
# =============================================================================

# Windows GBK 终端编码兼容
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _safe_print(*args, **kwargs):
    """安全打印，忽略无法编码的字符"""
    for arg in args:
        try:
            print(arg, **kwargs)
        except UnicodeEncodeError:
            print(str(arg).encode("ascii", errors="replace").decode("ascii"), **kwargs)


def _test_graph(quick: bool = False):
    """命令行快速测试 LangGraph 图

    Args:
        quick: True = 只跑快速测试（跳过行程生成，~15s）；False = 全量测试
    """
    t_start = time.time()

    _safe_print("=" * 60)
    mode_label = "Quick" if quick else "Full"
    _safe_print(f"LangGraph Graph Test —— ({mode_label})")
    _safe_print("=" * 60)

    graph = build_graph()

    # ---- 测试 1：定制——信息不全需追问 ----
    _safe_print("\n>>> Test 1: Planner — Missing Fields (ask follow-up)")
    _safe_print("-" * 40)

    result1 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去西安玩几天"}],
            "session_id": "test-p4-01",
            "customer_id": "cust-p4-01",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-01"}},
    )

    _safe_print(f"  Intent scores  : {result1.get('intent_scores')}")
    _safe_print(f"  Branch         : {result1.get('current_branch')}")
    _safe_print(f"  need_human     : {result1.get('need_human')}")
    _safe_print(f"  Need collected : { {k:v for k,v in result1.get('need',{}).items() if v} }")
    _safe_print(f"  Draft version  : {result1.get('draft', {}).get('version', 'N/A')}")
    _safe_print(f"  Reply (trunc)  : {result1.get('final_reply', '')[:200]}")

    if quick:
        _safe_print("\n>>> Test 2-4,7: SKIPPED (slow — LLM itinerary generation ~50s each)")
        _safe_print("    Use 'python -m api.main test' for full suite.")
    else:
        # ---- 测试 2：定制——完整信息生成草案 ----
        _safe_print("\n>>> Test 2: Planner — Full Info → Generate Itinerary")
        _safe_print("-" * 40)

        result2 = graph.invoke(
            {
                "messages": [{"role": "user", "content": "我想去西安玩4天，8月15号到，2个人，预算每人1500美元，喜欢历史文化，轻松节奏"}],
                "session_id": "test-p4-02",
                "customer_id": "cust-p4-02",
                "channel": "web",
                "language": "zh",
            },
            config={"configurable": {"thread_id": "test-p4-02"}},
        )

        _safe_print(f"  Intent scores  : {result2.get('intent_scores')}")
        _safe_print(f"  Branch         : {result2.get('current_branch')}")
        _safe_print(f"  need_human     : {result2.get('need_human')}")
        _safe_print(f"  Need collected : { {k:v for k,v in result2.get('need',{}).items() if v} }")
        _safe_print(f"  Draft version  : {result2.get('draft', {}).get('version', 'N/A')}")
        _safe_print(f"  Intent level   : {result2.get('intent_level')}")
        _safe_print(f"  Next action    : {result2.get('next_action')}")
        _safe_print(f"  Reply (trunc)  : {result2.get('final_reply', '')[:200]}")

        # ---- 测试 3：多轮收集——同一 thread 补全信息 ----
        _safe_print("\n>>> Test 3: Planner — Multi-turn info collection")
        _safe_print("-" * 40)

        _ = graph.invoke(
            {
                "messages": [{"role": "user", "content": "想去成都"}],
                "session_id": "test-p4-03",
                "customer_id": "cust-p4-03",
                "channel": "web",
                "language": "zh",
            },
            config={"configurable": {"thread_id": "test-p4-03"}},
        )

        result3b = graph.invoke(
            {
                "messages": [{"role": "user", "content": "5天，8月20号到，3个人，预算每人1000美元，喜欢美食"}],
            },
            config={"configurable": {"thread_id": "test-p4-03"}},
        )

        _safe_print(f"  Intent scores  : {result3b.get('intent_scores')}")
        _safe_print(f"  Branch         : {result3b.get('current_branch')}")
        _safe_print(f"  Need collected : { {k:v for k,v in result3b.get('need',{}).items() if v} }")
        _safe_print(f"  Draft version  : {result3b.get('draft', {}).get('version', 'N/A')}")
        _safe_print(f"  Intent level   : {result3b.get('intent_level')}")
        _safe_print(f"  Reply (trunc)  : {result3b.get('final_reply', '')[:200]}")

        # ---- 测试 4：修订循环——用户要求修改行程 ----
        _safe_print("\n>>> Test 4: Planner — Revision Loop")
        _safe_print("-" * 40)

        result4 = graph.invoke(
            {
                "messages": [{"role": "user", "content": "能不能多加点美食推荐的环节？"}],
            },
            config={"configurable": {"thread_id": "test-p4-02"}},
        )

        _safe_print(f"  Branch         : {result4.get('current_branch')}")
        _safe_print(f"  Draft version  : {result4.get('draft', {}).get('version', 'N/A')}")
        _safe_print(f"  Revision count : {result4.get('revision_count')}")
        _safe_print(f"  Intent level   : {result4.get('intent_level')}")
        _safe_print(f"  Next action    : {result4.get('next_action')}")
        _safe_print(f"  Reply (trunc)  : {result4.get('final_reply', '')[:200]}")

    # ---- 测试 5：客服 FAQ（Phase 3 回归）----
    _safe_print("\n>>> Test 5: CS — FAQ Regression")
    _safe_print("-" * 40)

    result5 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "签证需要什么材料？"}],
            "session_id": "test-p4-05",
            "customer_id": "cust-p4-05",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-05"}},
    )

    _safe_print(f"  Intent scores  : {result5.get('intent_scores')}")
    _safe_print(f"  need_human     : {result5.get('need_human')}")
    _safe_print(f"  Reply (trunc)  : {result5.get('final_reply', '')[:150]}")

    # ---- 测试 6：投诉转人工（Phase 3 回归）----
    _safe_print("\n>>> Test 6: CS — Complaint → Handoff (Regression)")
    _safe_print("-" * 40)

    result6 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我要投诉，导游完全不专业！"}],
            "session_id": "test-p4-06",
            "customer_id": "cust-p4-06",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p4-06"}},
    )

    _safe_print(f"  need_human     : {result6.get('need_human')}")
    _safe_print(f"  Reply (trunc)  : {result6.get('final_reply', '')[:150]}")

    if quick:
        _safe_print("\n>>> Test 7: SKIPPED")
    else:
        _safe_print("\n>>> Test 7: Operations Sync — Trip Confirmed")
        _safe_print("-" * 40)

        result7 = graph.invoke(
            {
                "messages": [{"role": "user", "content": "帮我规划北京3天，8月10号到，1个人，预算3000人民币"}],
                "session_id": "test-p5-07",
                "customer_id": "cust-p5-07",
                "channel": "web",
                "language": "zh",
            },
            config={"configurable": {"thread_id": "test-p5-07"}},
        )

        _safe_print(f"  Branch         : {result7.get('current_branch')}")
        _safe_print(f"  Draft version  : {result7.get('draft', {}).get('version', 'N/A')}")
        _safe_print(f"  Intent level   : {result7.get('intent_level')}")
        _safe_print(f"  Next action    : {result7.get('next_action')}")
        _safe_print(f"  Final reply OK : {'Yes' if result7.get('final_reply') else 'No'}")

    # ---- 测试 8：终态写入——转人工走 operations_sync ----
    _safe_print("\n>>> Test 8: Operations Sync — Handoff → CRM")
    _safe_print("-" * 40)

    result8 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我要投诉！你们的服务太差了，我要退款！"}],
            "session_id": "test-p5-08",
            "customer_id": "cust-p5-08",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p5-08"}},
    )

    _safe_print(f"  need_human     : {result8.get('need_human')}")
    _safe_print(f"  Reply length   : {len(result8.get('final_reply', ''))} chars")

    # ---- 测试 9：销售——询价 + 报价生成 ----
    _safe_print("\n>>> Test 9: Sales — Pricing Inquiry → Quote (Phase 6)")
    _safe_print("-" * 40)

    result9 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想去三亚玩5天，2个人，每人预算2000美元，能给我报个价吗？"}],
            "session_id": "test-p6-09",
            "customer_id": "cust-p6-09",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p6-09"}},
    )

    _safe_print(f"  Intent scores  : {result9.get('intent_scores')}")
    _safe_print(f"  Branch         : {result9.get('current_branch')}")
    _safe_print(f"  Intent level   : {result9.get('intent_level')}")
    _safe_print(f"  Next action    : {result9.get('next_action')}")
    _safe_print(f"  need_human     : {result9.get('need_human')}")
    _safe_print(f"  Reply (trunc)  : {result9.get('final_reply', '')[:200]}")

    # ---- 测试 10：销售——高意向购买 ----
    _safe_print("\n>>> Test 10: Sales — High Intent Purchase (Phase 6)")
    _safe_print("-" * 40)

    result10 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "这个报价不错，我要预订，怎么支付？"}],
        },
        config={"configurable": {"thread_id": "test-p6-09"}},
    )

    _safe_print(f"  Branch         : {result10.get('current_branch')}")
    _safe_print(f"  Intent level   : {result10.get('intent_level')}")
    _safe_print(f"  Next action    : {result10.get('next_action')}")
    _safe_print(f"  need_human     : {result10.get('need_human')}")
    _safe_print(f"  Reply (trunc)  : {result10.get('final_reply', '')[:200]}")

    # ---- 测试 11：运营——商家入驻咨询 ----
    _safe_print("\n>>> Test 11: Operations — Merchant Onboarding (Phase 6)")
    _safe_print("-" * 40)

    result11 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我是旅行社的，想在你们平台上架产品，需要什么资质？"}],
            "session_id": "test-p6-11",
            "customer_id": "cust-p6-11",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p6-11"}},
    )

    _safe_print(f"  Intent scores  : {result11.get('intent_scores')}")
    _safe_print(f"  Branch         : {result11.get('current_branch')}")
    _safe_print(f"  need_human     : {result11.get('need_human')}")
    _safe_print(f"  Reply (trunc)  : {result11.get('final_reply', '')[:200]}")

    # ---- 测试 12：运营——订单履约查询 ----
    _safe_print("\n>>> Test 12: Operations — Order Fulfillment Query (Phase 6)")
    _safe_print("-" * 40)

    result12 = graph.invoke(
        {
            "messages": [{"role": "user", "content": "我想查一下订单号 TK-2024-0815 的履约状态，酒店和车辆都确认好了吗？"}],
            "session_id": "test-p6-12",
            "customer_id": "cust-p6-12",
            "channel": "web",
            "language": "zh",
        },
        config={"configurable": {"thread_id": "test-p6-12"}},
    )

    _safe_print(f"  Branch         : {result12.get('current_branch')}")
    _safe_print(f"  need_human     : {result12.get('need_human')}")
    _safe_print(f"  Reply (trunc)  : {result12.get('final_reply', '')[:200]}")

    elapsed = time.time() - t_start
    test_count = "8" if quick else "12"
    _safe_print("\n" + "=" * 60)
    _safe_print(f"[OK] All {test_count} tests completed in {elapsed:.1f}s")
    _safe_print("=" * 60)


if __name__ == "__main__":
    # 用法：
    #   python -m api.main             → 启动 FastAPI 服务
    #   python -m api.main test        → 全量测试（12 组）
    #   python -m api.main test --quick → 快速测试（8 组，跳过行程生成）
    # Docker 不受影响（uvicorn api.main:app 不会触发此块）
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        quick = "--quick" in sys.argv
        _test_graph(quick=quick)
    else:
        import uvicorn
        uvicorn.run(
            "api.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
        )
