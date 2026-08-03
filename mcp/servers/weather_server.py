"""天气 MCP Server —— Open-Meteo 实时天气

API: Open-Meteo (https://open-meteo.com/)
费率: 免费，无需 API Key，10,000 calls/day
覆盖: 48 个中国城市 + 香港/澳门/台北

启动方式:
    python mcp/servers/weather_server.py
    → 监听 stdin，JSON-RPC 响应到 stdout
"""

from __future__ import annotations

import sys
import os

# 确保项目根在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server import MCPServer, tool
from tools.weather_real import fetch_weather

server = MCPServer("weather", version="1.0.0")


@tool(server, name="get_weather", description="查询指定城市在指定日期的天气情况（Open-Meteo 实时数据）。用于行程规划时获取目的地天气，以便合理安排户外/室内活动。",
      parameters={"city": "string", "date": "string"})
def get_weather(city: str, date: str) -> str:
    """查询城市天气

    Args:
        city: 城市中文名，如 "北京"、"三亚"、"西安"
        date: 日期，格式 YYYY-MM-DD

    Returns:
        格式化的天气描述（含温度、降水概率、风力、出行指数）
    """
    return fetch_weather(city, date)


if __name__ == "__main__":
    server.run()
