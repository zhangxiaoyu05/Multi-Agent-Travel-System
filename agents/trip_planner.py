"""定制 Agent——需求采集 + 行程草案生成

TripPlannerAgent 是系统中最复杂的 Agent，负责：
1. 从用户消息中提取出行需求字段（destination, days, date, pax, budget 等）
2. 检查必填项是否齐全，不全则追问
3. 调用天气、日历、库存工具获取实时数据
4. 基于数据生成 Markdown 格式的详细行程草案
5. 支持多轮修订——根据用户反馈重新生成行程
"""

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
        """用 LLM 从用户消息中提取出行需求字段

        只提取用户明确提到的信息，不猜测。
        """
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
            # 只保留非 None 的字段
            extracted = {}
            for field, value in result.model_dump().items():
                if value is not None:
                    extracted[field] = value
            return extracted
        except Exception:
            return {}

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
