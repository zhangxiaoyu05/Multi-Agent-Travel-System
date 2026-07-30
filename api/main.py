"""FastAPI 入口

启动方式：
    docker-compose up --build
    或
    python main.py
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# 启动时加载 .env
load_dotenv()

from api.schemas import ChatRequest, ChatResponse, TripDraftResponse
from graph.builder import build_graph

app = FastAPI(
    title="入境定制游 AI Agent",
    description="基于 LangGraph 的多 Agent 旅游规划系统（阿里百炼）",
    version="0.1.0",
)

# CORS：允许测试前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# 全局图实例（单例，通过 thread_id 隔离会话）
# =============================================================================

_graph = build_graph()


# 静态文件服务（前端页面）
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
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
    return {"message": "前端页面未找到，请访问 /docs 查看 API 文档"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """核心对话接口

    接收用户消息，通过 LangGraph 多 Agent 图处理，
    返回 AI 回复及结构化业务数据（行程草案、意向评分等）。

    - 使用 session_id 作为 thread_id，同一会话的消息保持上下文
    - 支持多轮需求收集、行程修订等复杂交互
    """
    try:
        # 构建初始 State
        initial_state = {
            "messages": [HumanMessage(content=req.message)],
            "session_id": req.session_id,
            "customer_id": req.customer_id,
            "channel": req.channel,
            "language": req.language,
        }

        # 通过图执行（async 避免阻塞 event loop）
        result = await _graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": req.session_id}},
        )

        # 构建行程草案子对象
        draft = result.get("draft", {}) or {}
        draft_response = None
        if draft.get("itinerary_md"):
            draft_response = TripDraftResponse(
                version=draft.get("version", 0),
                itinerary_md=draft["itinerary_md"],
                estimated_cost=draft.get("estimated_cost"),
                weather_summary=draft.get("weather_summary"),
            )

        # 构建响应
        return ChatResponse(
            reply=result.get("final_reply", "抱歉，处理您的请求时出现了问题。"),
            current_branch=result.get("current_branch"),
            draft=draft_response,
            need_human=result.get("need_human", False),
            intent_scores=result.get("intent_scores"),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"处理请求时出错：{str(e)}",
        )
