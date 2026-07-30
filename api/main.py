"""FastAPI 入口——入境定制游多 Agent 系统

启动方式：
    Docker:  docker-compose up --build
    本地:    python main.py

服务依赖：
    - MySQL 8.0（会话持久化 + LangGraph Checkpoint）
    - Redis 7（会话缓存 + 摘要缓存）
    - Milvus 单机（向量检索）
    - 阿里百炼（LLM + Embedding）
"""

import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
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

from api.schemas import ChatRequest, ChatResponse, TripDraftResponse
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

    # MySQL Checkpoint 表初始化
    try:
        from services.mysql import get_engine
        engine = get_engine()
        from sqlalchemy import text
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
        logger.info("MySQL checkpoint tables verified")
    except Exception as e:
        logger.warning(f"Checkpoint 表初始化跳过: {e}")

    logger.info("应用启动完成 ✓")
    logger.info(f"  LLM Router:  {os.getenv('ROUTER_MODEL', 'qwen-turbo')}")
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
    version="0.2.0",
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
    return {"message": "前端页面未找到，请访问 /docs 查看 API 文档", "version": "0.2.0"}


@app.get("/health")
async def health_check():
    """健康检查——返回各组件连接状态"""
    status = {
        "status": "ok",
        "version": "0.2.0",
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


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """核心对话接口

    接收用户消息，通过 LangGraph 多 Agent 图处理，
    返回 AI 回复及结构化业务数据。
    """
    try:
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "session_id": req.session_id,
            "customer_id": req.customer_id,
            "channel": req.channel,
            "language": req.language,
        }

        result = await _graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": req.session_id}},
        )

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
# SSE 流式对话接口
# =============================================================================

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
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
            "session_id": req.session_id,
            "customer_id": req.customer_id,
            "channel": req.channel,
            "language": req.language,
        }

        try:
            final_state = None
            async for event in _graph.astream(
                initial_state,
                config={"configurable": {"thread_id": req.session_id}},
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
