"""天气查询工具

支持双模式切换：
- TOOL_MODE=mock（默认）：返回 12 城市模拟数据
- TOOL_MODE=real：通过 Open-Meteo 免费 API 获取实时天气

使用方式：
    from tools.mock_weather import get_weather
    result = get_weather.invoke({"city": "北京", "date": "2026-08-15"})
"""

import os
import logging
from langchain.tools import tool

logger = logging.getLogger(__name__)

# 模拟城市天气数据（TOOL_MODE=mock 时使用）
_MOCK_WEATHER = {
    "北京": "晴间多云，22°C ~ 30°C，北风 3 级，降水概率 10%，适合出行指数：优秀",
    "西安": "晴转多云，24°C ~ 35°C，微风 2 级，降水概率 5%，适合出行指数：优秀（注意防晒）",
    "上海": "多云转阴，26°C ~ 33°C，东南风 3-4 级，降水概率 30%，适合出行指数：良好",
    "成都": "阴天间多云，22°C ~ 28°C，微风 1-2 级，降水概率 40%，适合出行指数：良好（建议带伞）",
    "广州": "雷阵雨转多云，26°C ~ 34°C，南风 2-3 级，降水概率 60%，适合出行指数：一般（避开午后雷雨）",
    "桂林": "多云，24°C ~ 31°C，微风 2 级，降水概率 20%，适合出行指数：优秀",
    "杭州": "小雨转阴，23°C ~ 29°C，东风 3 级，降水概率 50%，适合出行指数：良好（带伞）",
    "重庆": "多云，26°C ~ 33°C，微风 1-2 级，降水概率 25%，适合出行指数：良好",
    "昆明": "晴间多云，18°C ~ 25°C，西南风 2 级，降水概率 5%，适合出行指数：优秀（四季如春）",
    "拉萨": "晴，12°C ~ 22°C，微风 2 级，降水概率 5%，适合出行指数：优秀（注意高反）",
    "哈尔滨": "晴，18°C ~ 28°C，东北风 3 级，降水概率 10%，适合出行指数：优秀",
    "三亚": "多云转晴，27°C ~ 33°C，东南风 3-4 级，降水概率 15%，适合出行指数：优秀",
}


def _get_tool_mode() -> str:
    return os.getenv("TOOL_MODE", "mock").lower()


@tool
def get_weather(city: str, date: str) -> str:
    """查询指定城市在指定日期的天气情况。

    用于行程规划时获取目的地天气，以便合理安排户外/室内活动。
    当 TOOL_MODE=real 时使用 Open-Meteo 免费天气 API（无需 API Key）。

    Args:
        city: 城市名称（中文），如 "北京"、"西安"、"上海"
        date: 日期，格式 YYYY-MM-DD

    Returns:
        天气描述文本，包含天气状况、温度、风力、降水概率和出行指数。
    """
    # ---- Real mode: Open-Meteo ----
    if _get_tool_mode() == "real":
        try:
            from tools.weather_real import fetch_weather
            return fetch_weather(city, date)
        except Exception as e:
            logger.warning(f"Real weather API failed, falling back to mock: {e}")

    # ---- Mock mode (default) ----
    weather = _MOCK_WEATHER.get(city)
    if weather:
        return f"[{city}] {date}\n{weather}"
    return (
        f"[{city}] {date}\n"
        f"晴转多云，20°C ~ 28°C，微风 2-3 级，降水概率 15%，适合出行指数：良好\n"
        f"（注：{city} 暂无精确数据，以上为通用预报，建议出发前 3 天再次确认）"
    )
