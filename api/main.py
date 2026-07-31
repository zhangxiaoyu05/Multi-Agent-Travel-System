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

        logger.info("MySQL business tables verified")
    except Exception as e:
        logger.warning(f"业务表初始化跳过: {e}")

    logger.info("应用启动完成 ✓")
    logger.info(f"  LLM Router:  {os.getenv('ROUTER_MODEL', 'qwen-plus')}")
    logger.info(f"  LLM Agent:   {os.getenv('AGENT_MODEL', 'qwen3-max')}")
    logger.info(f"  Embedding:   {os.getenv('EMBEDDING_MODEL', 'text-embedding-v4')}")
    logger.info(f"  Checkpoint:  {os.getenv('CHECKPOINT_BACKEND', 'mysql')}")

    yield

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


@app.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    user: dict = Depends(get_current_user),
):
    """获取对话历史消息（从 LangGraph checkpoint 读取）"""
    from services.user_store import UserStore
    store = UserStore()
    conv = await store.get_conversation(conversation_id)
    if not conv or conv["user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 从 LangGraph checkpoint 加载状态
    try:
        config = {"configurable": {"thread_id": conversation_id}}
        state = await _graph.aget_state(config)
        if state and state.values:
            messages = state.values.get("messages", [])
            return {
                "conversation_id": conversation_id,
                "messages": [
                    {
                        "role": "user" if getattr(m, "type", "") == "human" else "agent",
                        "content": getattr(m, "content", ""),
                    }
                    for m in messages
                ],
            }
    except Exception:
        pass

    return {"conversation_id": conversation_id, "messages": []}


# =============================================================================
# 核心对话接口（需认证）
# =============================================================================


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """核心对话接口

    接收用户消息，通过 LangGraph 多 Agent 图处理，
    返回 AI 回复及结构化业务数据。
    """
    try:
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "session_id": req.conversation_id,
            "customer_id": user["user_id"],
            "channel": req.channel,
            "language": req.language,
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

        return ChatResponse(
            reply=result.get("final_reply", "抱歉，处理您的请求时出现了问题。"),
            current_branch=result.get("current_branch"),
            draft=draft_response,
            need_human=result.get("need_human", False),
            intent_scores=result.get("intent_scores"),
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
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "session_id": req.conversation_id,
            "customer_id": user["user_id"],
            "channel": req.channel,
            "language": req.language,
        }

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

            final_state = None
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

            # 构建最终响应
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
            else:
                yield f"event: error\ndata: {json.dumps({'message': '处理完成但无结果'}, ensure_ascii=False)}\n\n"

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
