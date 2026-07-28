"""本地快速调试入口

直接运行: python main.py
效果等同于: uvicorn api.main:app --reload
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
