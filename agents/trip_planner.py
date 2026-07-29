"""定制 Agent——需求采集 + 行程草案生成

TripPlannerAgent 是系统中最复杂的 Agent，负责：
1. 从用户消息中提取出行需求字段（destination, days, date, pax, budget 等）
2. 检查必填项是否齐全，不全则追问
3. 调用天气、日历、库存工具获取实时数据
4. 基于数据生成 Markdown 格式的详细行程草案
5. 支持多轮修订——根据用户反馈重新生成行程
"""

import re
from pydantic import BaseModel, Field
from agents.base import BaseAgent
from graph.state import AgentState
from tools.mock_weather import get_weather
from tools.mock_calendar import query_calendar
from tools.mock_inventory import query_inventory
from services.llm import get_agent_llm, get_router_llm
from prompts import load_prompt


# =============================================================================
# 必填项定义
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


# =============================================================================
# Regex 快速提取（优化：避免 LLM 调用解析简单字段）
# =============================================================================

# 预定义目的地城市列表
_CITIES = [
    "北京", "西安", "上海", "成都", "广州", "桂林", "杭州", "重庆",
    "昆明", "拉萨", "哈尔滨", "三亚", "深圳", "南京", "武汉", "苏州",
    "厦门", "大理", "丽江", "张家界", "黄山", "洛阳", "开封", "青岛", "大连",
    "长沙", "贵阳", "乌鲁木齐", "呼和浩特", "西宁", "兰州", "银川", "南宁",
]

# 主题关键词映射
_THEME_MAP = {
    "历史": "历史文化", "文化": "历史文化", "古迹": "历史文化",
    "自然": "自然风光", "风景": "自然风光", "山水": "自然风光",
    "美食": "美食", "吃": "美食", "小吃": "美食",
}

# 节奏关键词映射
_PACE_MAP = {
    "轻松": "轻松", "休闲": "轻松", "慢": "轻松",
    "适中": "适中", "中等": "适中", "适度": "适中",
    "紧凑": "紧凑", "赶": "紧凑", "快": "紧凑",
}


def _extract_fields_regex(user_msg: str) -> dict:
    """用正则 + 关键词从用户消息中快速提取行程需求字段

    在 <1ms 内完成，免除 1 次 LLM 调用。
    只提取明确匹配的字段，不猜测。

    Returns:
        dict 包含提取到的字段（未匹配的字段不出现在 dict 中）
    """
    extracted: dict = {}

    # ---- 目的地：城市列表匹配 ----
    for city in _CITIES:
        if city in user_msg:
            extracted["destination"] = city
            break

    # ---- 天数：X天 / X日 ----
    m = re.search(r'(\d+)\s*[天日]', user_msg)
    if m:
        extracted["days"] = int(m.group(1))

    # ---- 人数：X人 / X个 / X位 ----
    m = re.search(r'(\d+)\s*[人个位]', user_msg)
    if m:
        extracted["pax"] = int(m.group(1))

    # ---- 日期：优先匹配完整日期，再匹配 "M月D日/号" ----
    m = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日号]?', user_msg)
    if m:
        extracted["arrival_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m = re.search(r'(\d{1,2})月(\d{1,2})[日号]', user_msg)
        if m:
            extracted["arrival_date"] = f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    # ---- 预算：$X / ¥X / X美元 / X元 ----
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

    # ---- 主题：关键词匹配 ----
    for keyword, theme in _THEME_MAP.items():
        if keyword in user_msg:
            extracted["theme"] = theme
            break

    # ---- 节奏：关键词匹配 ----
    for keyword, pace in _PACE_MAP.items():
        if keyword in user_msg:
            extracted["pace"] = pace
            break

    # ---- 特殊需求 ----
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
# 需求提取 Schema
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
    """定制 Agent

    使用 qwen-plus 做需求提取和行程生成。
    tools 中包含 weather/calendar/inventory 三个数据查询工具。
    """

    def __init__(self):
        llm = get_agent_llm()
        tools = [get_weather, query_calendar, query_inventory]
        system_prompt = load_prompt("trip_planner.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    def run(self, state: AgentState) -> dict:
        """执行定制逻辑

        流程：
        1. 从用户消息中提取出行需求字段
        2. 与 checkpoint 中已有的 need 合并
        3. 检查必填项 → 缺失则生成追问
        4. 齐全则调用 tools → LLM 生成行程草案

        Args:
            state: 当前 AgentState

        Returns:
            dict 包含 need, draft, final_reply
        """
        user_msg = self._get_user_message(state)
        raw_need = state.get("need")
        existing_need = raw_need if raw_need else {}
        revision_count = state.get("revision_count", 0)

        if not user_msg:
            return {
                "need": existing_need,
                "final_reply": "您好！请告诉我您的出行需求（目的地、天数、日期、人数、预算），我来为您定制专属行程。",
            }

        # Step 1: 提取需求字段
        # 优化：修订模式下跳过字段提取（用户消息是反馈而非新的行程需求）
        if revision_count > 0:
            merged_need = existing_need
        else:
            extracted = self._extract_fields(user_msg, existing_need)
            merged_need = {**existing_need, **extracted}

        # Step 2: 检查必填项
        missing = [f for f in REQUIRED_FIELDS if not merged_need.get(f)]

        if missing:
            return self._ask_missing_fields(missing, merged_need)

        # Step 3: 必填项齐全 → 调用工具获取数据
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

        # Step 4: 构建生成提示词
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
        response = self.llm.invoke([
            {"role": "system", "content": self.system_prompt},
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
        """从用户消息中提取出行需求字段

        优化策略：先用 regex 快速提取（<1ms），
        如果必填项全部匹配则直接返回，否则走 LLM 兜底。

        只提取用户明确提到的信息，不猜测。
        """
        # Step 1: Regex 快速提取
        regex_extracted = _extract_fields_regex(user_msg)

        # Step 2: 检查必填项是否全部被 regex 覆盖
        regex_keys = set(regex_extracted.keys())
        required_set = set(REQUIRED_FIELDS)
        existing_set = {k for k, v in existing_need.items() if v}

        # 如果 regex 已覆盖所有当前缺失的必填项，直接返回（跳过 LLM）
        still_missing = required_set - existing_set - regex_keys
        if not still_missing:
            return regex_extracted

        # Step 3: Regex 不完整 → LLM 兜底提取
        # 使用 router LLM（轻量）做结构化提取
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

            # 合并：regex 结果优先，LLM 补充缺失字段
            llm_extracted = {}
            for field, value in result.model_dump().items():
                if value is not None:
                    llm_extracted[field] = value

            # regex 结果更可靠（精确匹配），LLM 作为补充
            merged = {**llm_extracted, **regex_extracted}
            return merged

        except Exception:
            # LLM 也失败了 → 只返回 regex 结果
            return regex_extracted

    def _ask_missing_fields(self, missing: list, need: dict) -> dict:
        """生成友好的追问消息，引导用户补充缺失信息"""
        missing_cn = [FIELD_CN_NAMES.get(f, f) for f in missing]

        lines = ["好的！还差一点点信息就能为您生成专属行程了：\n"]
        for i, field_name in enumerate(missing_cn, 1):
            lines.append(f"{i}. **{field_name}**")

        lines.append(f"\n请直接回复我这些信息就好~")
        # 如果已有部分信息，展示已收集的内容
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


# 模块级单例
_agent_instance: TripPlannerAgent | None = None


def get_trip_planner_agent() -> TripPlannerAgent:
    """获取定制 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = TripPlannerAgent()
    return _agent_instance
