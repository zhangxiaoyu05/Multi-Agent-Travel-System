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

        # 🧠 加载用户画像和中期偏好
        profile = state.get("user_profile", {}) or {}
        prefs = state.get("user_preferences", {}) or {}

        if not user_msg:
            return {
                "need": existing_need,
                "final_reply": "您好！请告诉我您的出行需求（目的地、天数、日期、人数、预算），我来为您定制专属行程。",
            }

        # Step 1: 提取需求字段
        if revision_count > 0:
            merged_need = existing_need
        else:
            # 🛑 从历史用户消息中也提取字段（防止打断后丢失已提供的信息）
            history_need = self._extract_from_history(state)
            extracted = self._extract_fields(user_msg, existing_need)
            # 合并：历史提取 < 当前提取（当前消息优先级更高）
            merged_need = {**history_need, **existing_need, **extracted}
            # 🧠 从画像/偏好自动补全缺失字段（不覆盖用户明确提供的信息）
            merged_need = self._enrich_from_memory(
                merged_need, profile, prefs
            )

        # Step 2: 检查必填项
        missing = [f for f in REQUIRED_FIELDS if not merged_need.get(f)]
        if missing:
            result = self._ask_missing_fields(missing, merged_need, profile)
            # 🧠 画像自动补全后字段齐全 → 跳过追问，继续生成
            if result.get("_auto_filled"):
                merged_need = result["need"]
            else:
                return result

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

        # 🧠 构建用户画像上下文
        profile_context = self._build_profile_context(profile, prefs)

        generation_prompt = f"""
请根据以下信息为客户生成详细行程草案：

## 客户画像（来自长期记忆）
{profile_context if profile_context else '（暂无历史画像数据）'}

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
            "current_branch": "trip_planner",
        }

    # =========================================================================
    # 私有方法
    # =========================================================================

    @staticmethod
    def _extract_from_history(state: AgentState) -> dict:
        """从最近的历史用户消息中提取需求字段（防止打断后丢失上下文）

        遍历 state["messages"] 中最近 8 条 HumanMessage，
        用 regex 提取字段，返回合并后的 need dict。
        （后续与当前消息的正则提取结果合并，当前消息优先级更高）
        """
        from langchain_core.messages import HumanMessage
        result: dict = {}
        messages = state.get("messages", []) or []
        # 从后往前取 HumanMessage（最近的优先），但只处理倒数第2条起
        # （最后一条就是当前消息，跳过）
        user_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        # 排除最后一条（当前消息），从近到远处理
        for m in reversed(user_msgs[:-1]):
            fields = _extract_fields_regex(m.content)
            # 只填充 result 中尚未有的字段（越近的消息优先级越高）
            for k, v in fields.items():
                if v and k not in result:
                    result[k] = v
            # 限制处理最近 5 条用户消息
            if len([k for k, v in result.items() if v]) >= 5:
                break
        return result

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

    # =========================================================================
    # 🧠 记忆集成方法
    # =========================================================================

    @staticmethod
    def _fmt_budget(budget_val) -> str | None:
        """格式化 budget_range（支持 JSON 对象和字符串）"""
        if not budget_val:
            return None
        if isinstance(budget_val, dict):
            lo, hi, cur = budget_val.get("min"), budget_val.get("max"), budget_val.get("currency", "USD")
            parts = [f"{lo}" if lo else "", f"{hi}" if hi else "", cur]
            parts = [p for p in parts if p]
            return "/".join(parts) if parts else None
        return str(budget_val)

    def _enrich_from_memory(self, need: dict, profile: dict, prefs: dict) -> dict:
        """从画像/偏好自动补全缺失的 need 字段（不覆盖已有值）"""
        merged = dict(need)

        # 预算：profile.budget_range 优先
        if not merged.get("budget"):
            budget_str = self._fmt_budget(profile.get("budget_range"))
            if not budget_str:
                budget_str = prefs.get("budget_range")
            if budget_str:
                merged["budget"] = budget_str

        # 主题：profile.interests 优先
        if not merged.get("theme"):
            interests = profile.get("interests") or prefs.get("interests") or []
            if isinstance(interests, str):
                interests = [i.strip() for i in interests.split(",")]
            if interests:
                merged["theme"] = interests[0] if len(interests) == 1 else "/".join(interests[:3])

        # 节奏
        if not merged.get("pace"):
            pace = profile.get("travel_style") or prefs.get("travel_style")
            if pace:
                merged["pace"] = pace

        # 特殊需求
        if not merged.get("special_requests"):
            needs = profile.get("special_needs") or prefs.get("special_needs") or []
            if isinstance(needs, str):
                needs = [n.strip() for n in needs.split(",")]
            if needs:
                merged["special_requests"] = ", ".join(needs)

        return merged

    def _build_profile_context(self, profile: dict, prefs: dict) -> str:
        """构建注入 prompt 的用户画像上下文"""
        lines = []
        if profile.get("nationality"):
            lines.append(f"- 国籍：{profile['nationality']}")
        if profile.get("preferred_language"):
            lines.append(f"- 语言偏好：{profile['preferred_language']}")
        if profile.get("preferred_destinations"):
            dests = profile["preferred_destinations"]
            if isinstance(dests, str):
                dests = [d.strip() for d in dests.split(",")]
            lines.append(f"- 意向目的地：{', '.join(dests)}")

        budget_str = self._fmt_budget(profile.get("budget_range"))
        if budget_str:
            lines.append(f"- 预算范围：{budget_str}")
        if profile.get("travel_style"):
            lines.append(f"- 节奏偏好：{profile['travel_style']}")
        if profile.get("interests"):
            interests = profile["interests"]
            if isinstance(interests, str):
                interests = [i.strip() for i in interests.split(",")]
            lines.append(f"- 兴趣标签：{', '.join(interests)}")
        if profile.get("travel_companion"):
            lines.append(f"- 同行人：{profile['travel_companion']}")
        if profile.get("special_needs"):
            needs = profile["special_needs"]
            if isinstance(needs, str):
                needs = [n.strip() for n in needs.split(",")]
            lines.append(f"- 特殊需求：{', '.join(needs)}")
        if profile.get("preferred_seasons"):
            seasons = profile["preferred_seasons"]
            if isinstance(seasons, str):
                seasons = [s.strip() for s in seasons.split(",")]
            lines.append(f"- 偏好季节：{', '.join(seasons)}")

        # 中期偏好补充
        if prefs and not profile.get("preferred_destinations"):
            dests = prefs.get("preferred_destinations") or []
            if dests:
                lines.append(f"- 最近意向目的地（自动提取）：{', '.join(dests)}")
            if prefs.get("confidence"):
                lines.append(f"- 偏好置信度：{prefs['confidence']:.0%}")

        return "\n".join(lines) if lines else ""

    def _ask_missing_fields(self, missing: list, need: dict, profile: dict | None = None) -> dict:
        """生成追问消息，但跳过画像中已知的字段"""
        profile = profile or {}
        # 🧠 过滤：画像中已有值的字段不再追问
        profile_hints = {
            "budget": self._fmt_budget(profile.get("budget_range")),
            "destination": ", ".join(profile.get("preferred_destinations", [])),
        }
        actually_missing = [
            f for f in missing
            if not profile_hints.get(f)  # 画像中没有此字段的答案才追问
        ]

        # 如果画像能填补所有缺失字段，自动补全
        if not actually_missing:
            for f in missing:
                if profile_hints.get(f):
                    need[f] = profile_hints[f]
            # 递归检查
            still_missing = [f for f in REQUIRED_FIELDS if not need.get(f)]
            if not still_missing:
                # 所有字段齐全，跳到生成
                return {"need": need, "_auto_filled": True}

        missing_cn = [FIELD_CN_NAMES.get(f, f) for f in actually_missing or missing]

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

        # 🧠 提示已知偏好（让用户知道 AI 了解他们）
        if profile:
            hints = []
            if profile.get("travel_style"):
                hints.append(f"偏好节奏：{profile['travel_style']}")
            if profile.get("interests"):
                hints.append(f"兴趣：{', '.join(profile['interests'])}")
            if profile.get("travel_companion"):
                hints.append(f"同行人：{profile['travel_companion']}")
            if hints:
                lines.append(f"\n💡 根据您的历史偏好，已了解：{' | '.join(hints)}")

        return {
            "need": need,
            "final_reply": "\n".join(lines),
            "current_branch": "trip_planner",
        }


_agent_instance: TripPlannerAgent | None = None


def get_trip_planner_agent() -> TripPlannerAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = TripPlannerAgent()
    return _agent_instance
