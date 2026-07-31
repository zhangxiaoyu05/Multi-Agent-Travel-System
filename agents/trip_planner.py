"""定制 Agent——需求采集 + 行程草案生成（异步版）

TripPlannerAgent 不套用标准 tool-calling 循环，原因：
1. 需求提取走 regex + LLM 双通道
2. 工具调用是强制性的（每次都查天气/日历/库存）
3. 行程生成 prompt 是动态构建的
"""

import re
from pydantic import BaseModel, Field
from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_weather import get_weather
from tools.mock_calendar import query_calendar
from tools.mock_inventory import query_inventory
from services.llm import get_agent_llm, get_router_llm
from prompts import load_prompt, get_language_instruction


# =============================================================================
# 常量
# =============================================================================

REQUIRED_FIELDS = ["destination", "days", "arrival_date", "pax", "budget"]

FIELD_CN_NAMES = {
    "destination": "目的地城市",
    "days": "行程天数",
    "arrival_date": "抵达日期（如 2026-08-15）",
    "pax": "出行人数",
    "budget": "预算范围（如 $2000/人 或 ¥5000/人）",
    "theme": "偏好主题（历史文化 / 自然风光 / 美食 / 综合）",
    "pace": "节奏偏好（轻松 / 适中 / 紧凑）",
    "special_requests": "特殊需求（如素食、轮椅、带小孩等）",
}

_CITIES = [
    "北京", "西安", "上海", "成都", "广州", "桂林", "杭州", "重庆",
    "昆明", "拉萨", "哈尔滨", "三亚", "深圳", "南京", "武汉", "苏州",
    "厦门", "大理", "丽江", "张家界", "黄山", "洛阳", "开封", "青岛", "大连",
    "长沙", "贵阳", "乌鲁木齐", "呼和浩特", "西宁", "兰州", "银川", "南宁",
]

_THEME_MAP = {
    "历史": "历史文化", "文化": "历史文化", "古迹": "历史文化",
    "自然": "自然风光", "风景": "自然风光", "山水": "自然风光",
    "美食": "美食", "吃": "美食", "小吃": "美食",
}

_PACE_MAP = {
    "轻松": "轻松", "休闲": "轻松", "慢": "轻松",
    "适中": "适中", "中等": "适中", "适度": "适中",
    "紧凑": "紧凑", "赶": "紧凑", "快": "紧凑",
}


# =============================================================================
# Regex 快速提取（<1ms, 无 LLM 调用）
# =============================================================================

def _extract_fields_regex(user_msg: str) -> dict:
    """正则 + 关键词快速提取行程字段"""
    extracted: dict = {}

    # 目的地
    for city in _CITIES:
        if city in user_msg:
            extracted["destination"] = city
            break

    # 天数
    m = re.search(r'(\d+)\s*[天日]', user_msg)
    if m:
        extracted["days"] = int(m.group(1))

    # 人数
    m = re.search(r'(\d+)\s*[人个位]', user_msg)
    if m:
        extracted["pax"] = int(m.group(1))

    # 日期
    m = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日号]?', user_msg)
    if m:
        extracted["arrival_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m = re.search(r'(\d{1,2})月(\d{1,2})[日号]', user_msg)
        if m:
            extracted["arrival_date"] = f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # 预算
    m = re.search(r'[¥\$]\s*(\d[\d,]*)', user_msg)
    if m:
        extracted["budget"] = f"${m.group(1)}"
    else:
        m = re.search(r'(\d+)\s*(?:美元|美金)', user_msg)
        if m:
            extracted["budget"] = f"${m.group(1)}"
        else:
            m = re.search(r'(\d+)\s*(?:人民币|元|块)', user_msg)
            if m:
                extracted["budget"] = f"¥{m.group(1)}"
            else:
                m = re.search(r'预算\s*(\d[\d,]*)', user_msg)
                if m:
                    extracted["budget"] = f"¥{m.group(1)}"

    # 主题
    for keyword, theme in _THEME_MAP.items():
        if keyword in user_msg:
            extracted["theme"] = theme
            break

    # 节奏
    for keyword, pace in _PACE_MAP.items():
        if keyword in user_msg:
            extracted["pace"] = pace
            break

    # 特殊需求
    if "素食" in user_msg or "吃素" in user_msg:
        extracted["special_requests"] = "素食需求"
    if "轮椅" in user_msg:
        existing = extracted.get("special_requests", "")
        extracted["special_requests"] = (existing + "；轮椅需求").strip("；")
    if "小孩" in user_msg or "带娃" in user_msg or "亲子" in user_msg:
        existing = extracted.get("special_requests", "")
        extracted["special_requests"] = (existing + "；带小孩").strip("；")

    return extracted


# =============================================================================
# LLM 需求提取 Schema
# =============================================================================

class NeedExtract(BaseModel):
    """LLM 从用户消息中提取的出行需求"""
    destination: str | None = Field(default=None, description="目的地城市")
    days: int | None = Field(default=None, description="行程天数")
    arrival_date: str | None = Field(default=None, description="抵达日期 YYYY-MM-DD")
    pax: int | None = Field(default=None, description="出行人数")
    budget: str | None = Field(default=None, description="预算")
    theme: str | None = Field(default=None, description="偏好主题")
    pace: str | None = Field(default=None, description="节奏偏好")
    special_requests: str | None = Field(default=None, description="特殊需求")


# =============================================================================
# TripPlannerAgent
# =============================================================================

class TripPlannerAgent(BaseAgent):
    """定制 Agent——需求提取 + 工具调用 + 行程生成"""

    def __init__(self):
        llm = get_agent_llm()
        tools = [get_weather, query_calendar, query_inventory]
        system_prompt = load_prompt("trip_planner.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    async def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        language = self._get_language(state)
        lang_instr = get_language_instruction(language)
        raw_need = state.get("need")
        existing_need = raw_need if raw_need else {}
        revision_count = state.get("revision_count", 0)

        if not user_msg:
            return {
                "need": existing_need,
                "final_reply": "您好！请告诉我您的出行需求（目的地、天数、日期、人数、预算），我来为您定制专属行程。",
            }

        # Step 1: 提取需求字段
        if revision_count > 0:
            merged_need = existing_need
        else:
            extracted = self._extract_fields(user_msg, existing_need)
            merged_need = {**existing_need, **extracted}

        # Step 2: 检查必填项
        missing = [f for f in REQUIRED_FIELDS if not merged_need.get(f)]
        if missing:
            return self._ask_missing_fields(missing, merged_need)

        # Step 3: 调用工具（同步，因为 Mock 工具是同步的）
        weather_info = get_weather.invoke({
            "city": merged_need["destination"],
            "date": merged_need["arrival_date"],
        })
        calendar_info = query_calendar.invoke({
            "date": merged_need["arrival_date"],
        })
        inventory_info = query_inventory.invoke({
            "city": merged_need["destination"],
            "date": merged_need["arrival_date"],
            "pax": merged_need["pax"],
        })

        # Step 4: 异步生成行程草案
        revision_note = ""
        if revision_count > 0:
            revision_note = (
                f"\n\n【重要】这是第 {revision_count} 次修订。"
                f"用户的修改意见是：「{user_msg}」"
                f"\n请在原有行程基础上据此调整，并在回复开头说明「已根据您的反馈调整了...」。"
            )

        generation_prompt = f"""
请根据以下信息为客户生成详细行程草案：

## 客户需求
- 目的地：{merged_need['destination']}
- 行程天数：{merged_need['days']} 天
- 抵达日期：{merged_need['arrival_date']}
- 出行人数：{merged_need['pax']} 人
- 预算范围：{merged_need['budget']}
- 偏好主题：{merged_need.get('theme', '经典必游')}
- 节奏偏好：{merged_need.get('pace', '适中')}
- 特殊需求：{merged_need.get('special_requests', '无')}

## 实时数据
### 天气信息
{weather_info}

### 日期信息
{calendar_info}

### 库存信息
{inventory_info}
{revision_note}

请生成完整的 Markdown 格式行程草案。
"""
        response = await self.llm.ainvoke([
            {"role": "system", "content": self.system_prompt + lang_instr},
            {"role": "user", "content": generation_prompt},
        ])

        # Step 5: 构建草案
        current_draft = state.get("draft", {}) or {}
        draft_version = current_draft.get("version", 0) + 1

        return {
            "need": merged_need,
            "draft": {
                "version": draft_version,
                "itinerary_md": response.content,
                "weather_summary": str(weather_info),
            },
            "final_reply": response.content,
            "current_branch": "planner",
        }

    # =========================================================================
    # 私有方法
    # =========================================================================

    def _extract_fields(self, user_msg: str, existing_need: dict) -> dict:
        """Regex + LLM 双通道提取需求字段"""
        regex_extracted = _extract_fields_regex(user_msg)

        # 检查 regex 是否已覆盖所有缺失的必填项
        regex_keys = set(regex_extracted.keys())
        required_set = set(REQUIRED_FIELDS)
        existing_set = {k for k, v in existing_need.items() if v}
        still_missing = required_set - existing_set - regex_keys

        if not still_missing:
            return regex_extracted

        # LLM 兜底
        router_llm = get_router_llm()
        structured_llm = router_llm.with_structured_output(NeedExtract)

        existing_str = ", ".join(
            f"{FIELD_CN_NAMES.get(k, k)}={v}"
            for k, v in existing_need.items() if v
        ) or "无"

        try:
            result: NeedExtract = structured_llm.invoke([
                {
                    "role": "system",
                    "content": (
                        "你是一个信息提取助手。从用户消息中提取旅行需求字段。\n"
                        "规则：\n"
                        "1. 只提取用户明确提到的信息，不要猜测\n"
                        "2. 日期统一转为 YYYY-MM-DD 格式（如 7月30号 → 2026-07-30）\n"
                        "3. 天数提取纯数字（如 '3天' → 3）\n"
                        "4. 预算保留原样（如 '$2000'）\n"
                        f"5. 已收集的信息：{existing_str}（如果用户消息中提供了新值，覆盖旧值）\n"
                        "6. 如果用户消息中没有某个字段，设置为 null"
                    ),
                },
                {"role": "user", "content": user_msg},
            ])

            llm_extracted = {}
            for field, value in result.model_dump().items():
                if value is not None:
                    llm_extracted[field] = value

            return {**llm_extracted, **regex_extracted}

        except Exception:
            return regex_extracted

    def _ask_missing_fields(self, missing: list, need: dict) -> dict:
        missing_cn = [FIELD_CN_NAMES.get(f, f) for f in missing]

        lines = ["好的！还差一点点信息就能为您生成专属行程了：\n"]
        for i, field_name in enumerate(missing_cn, 1):
            lines.append(f"{i}. **{field_name}**")

        lines.append("\n请直接回复我这些信息就好~")
        filled = {k: v for k, v in need.items() if v}
        if filled:
            lines.append("\n已确认的信息：")
            for k, v in filled.items():
                cn_name = FIELD_CN_NAMES.get(k, k)
                lines.append(f"  - {cn_name}：{v}")

        return {
            "need": need,
            "final_reply": "\n".join(lines),
            "current_branch": "planner",
        }


_agent_instance: TripPlannerAgent | None = None


def get_trip_planner_agent() -> TripPlannerAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = TripPlannerAgent()
    return _agent_instance
