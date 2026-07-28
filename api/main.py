"""FastAPI 入口

启动方式：
    docker-compose up --build
    或
    python main.py
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 启动时加载 .env
load_dotenv()

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


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}
