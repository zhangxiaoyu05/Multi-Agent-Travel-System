"""真实天气 API——Open-Meteo（免费，无需 API Key）

API: https://open-meteo.com/en/docs
费率: 免费，非商业用途 10,000 calls/day，无需注册

通过 TOOL_MODE=real 激活。默认使用 mock 数据。
"""

import logging
import httpx
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

# Open-Meteo API endpoint
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# 城市 → (纬度, 经度) 坐标映射
CITY_COORDS: dict[str, tuple[float, float]] = {
    # 华北
    "北京": (39.9042, 116.4074),
    "天津": (39.3434, 117.3616),
    "石家庄": (38.0428, 114.5149),
    "太原": (37.8706, 112.5489),
    "呼和浩特": (40.8424, 111.7490),
    # 东北
    "哈尔滨": (45.8038, 126.5350),
    "沈阳": (41.8057, 123.4315),
    "长春": (43.8171, 125.3235),
    "大连": (38.9140, 121.6147),
    # 华东
    "上海": (31.2304, 121.4737),
    "南京": (32.0603, 118.7969),
    "杭州": (30.2741, 120.1551),
    "苏州": (31.2990, 120.5853),
    "青岛": (36.0671, 120.3826),
    "厦门": (24.4798, 118.0894),
    "黄山": (30.1340, 118.1610),
    # 华中
    "武汉": (30.5928, 114.3055),
    "长沙": (28.2282, 112.9388),
    "郑州": (34.7466, 113.6253),
    "洛阳": (34.6181, 112.4540),
    "张家界": (29.1170, 110.4782),
    # 华南
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "桂林": (25.2736, 110.2898),
    "三亚": (18.2528, 109.5120),
    "海口": (20.0440, 110.1999),
    "南宁": (22.8170, 108.3665),
    # 西南
    "成都": (30.5728, 104.0668),
    "重庆": (29.4316, 106.9123),
    "昆明": (25.0389, 102.7183),
    "丽江": (26.8721, 100.2299),
    "大理": (25.6065, 100.2676),
    "贵阳": (26.6470, 106.6302),
    "拉萨": (29.6500, 91.1000),
    "西双版纳": (21.9961, 100.7988),
    "香格里拉": (27.8256, 99.7027),
    # 西北
    "西安": (34.3416, 108.9398),
    "兰州": (36.0611, 103.8343),
    "敦煌": (40.1421, 94.6620),
    "乌鲁木齐": (43.8256, 87.6168),
    "西宁": (36.6171, 101.7785),
    "银川": (38.4872, 106.2309),
    # 香港/澳门/台湾
    "香港": (22.3193, 114.1694),
    "澳门": (22.1987, 113.5439),
    "台北": (25.0330, 121.5654),
}

# WMO Weather Code → 中文描述
# https://open-meteo.com/en/docs#weathervariables
_WEATHER_CODES: dict[int, str] = {
    0: "晴",
    1: "少云",
    2: "多云",
    3: "阴天",
    45: "有雾",
    48: "雾凇",
    51: "小雨",
    53: "中雨",
    55: "大雨",
    56: "冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "暴雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "冰雹雷暴",
    99: "大冰雹雷暴",
}


def fetch_weather(city: str, target_date: str) -> str:
    """从 Open-Meteo 获取真实天气数据并格式化为中文描述。

    Args:
        city: 城市中文名
        target_date: 日期 YYYY-MM-DD

    Returns:
        格式化的天气描述字符串，格式与 mock 工具一致
    """
    coords = CITY_COORDS.get(city)
    if not coords:
        return (
            f"【{city}】{target_date}\n"
            f"⚠️ 该城市暂时不在支持列表中，无法获取实时天气数据。\n"
            f"请尝试其他主要旅游城市。"
        )

    lat, lon = coords

    try:
        # 解析目标日期，限制为未来7天预报
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
        today = date.today()
        days_ahead = (target - today).days

        if days_ahead < 0:
            return f"【{city}】{target_date}\n⚠️ 无法获取历史天气数据，请查询今日及未来7天。"

        if days_ahead > 6:
            logger.info(f"Weather forecast limited to 7 days, requested {target_date} ({days_ahead}d ahead)")
            # 仍然请求，但 Open-Meteo 可能不返回这么远的数据

        resp = httpx.get(_OPEN_METEO_URL, params={
            "latitude": lat,
            "longitude": lon,
            "daily": [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "weather_code",
                "wind_speed_10m_max",
            ],
            "timezone": "Asia/Shanghai",
            "forecast_days": min(16, max(7, days_ahead + 1)),
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        times = daily.get("time", [])

        # 查找目标日期
        try:
            idx = times.index(target_date)
        except ValueError:
            # 取最近可用日期
            if times:
                idx = 0
                actual_date = times[0]
            else:
                return f"【{city}】{target_date}\n⚠️ 暂时无法获取天气数据，请稍后重试。"

        actual_date = times[idx]
        temp_max = daily["temperature_2m_max"][idx]
        temp_min = daily["temperature_2m_min"][idx]
        precip = daily["precipitation_probability_max"][idx]
        weather_code = daily["weather_code"][idx]
        wind_speed = daily["wind_speed_10m_max"][idx]

        condition = _WEATHER_CODES.get(weather_code, f"天气代码{weather_code}")

        # 出行指数
        if precip < 20 and weather_code <= 2:
            travel_index = "✅ 适合出行指数：优秀"
        elif precip < 50 and weather_code <= 3:
            travel_index = "👍 适合出行指数：良好"
        elif precip < 70:
            travel_index = "⚠️ 适合出行指数：一般（建议备雨具）"
        else:
            travel_index = "❌ 适合出行指数：较差（建议调整行程）"

        return (
            f"【{city}】{actual_date} 天气（Open-Meteo 实时数据）\n"
            f"🌤️ 天气：{condition}\n"
            f"🌡️ 温度：{temp_min}°C ~ {temp_max}°C\n"
            f"🌧️ 降水概率：{precip}%\n"
            f"🍃 风力：{wind_speed} km/h\n"
            f"{travel_index}"
        )

    except httpx.HTTPError as e:
        logger.error(f"Open-Meteo API error: {e}")
        return (
            f"【{city}】{target_date}\n"
            f"⚠️ 天气服务暂时不可用（{e}），请稍后重试。"
        )
    except Exception as e:
        logger.error(f"Weather fetch error for {city}/{target_date}: {e}")
        return (
            f"【{city}】{target_date}\n"
            f"⚠️ 获取天气数据时出错，请稍后重试。"
        )
