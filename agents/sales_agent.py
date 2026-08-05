"""销售 Agent——销售顾问（Phase 20 重写）

Pipeline 五阶段模型：
    LEAD → QUALIFIED → NEGOTIATION → CLOSING → WON
      │                                      │
      └──────────────────────────────────────┴──→ LOST

- LEAD: 有购买意向但无行程方案 → 引导去 trip_planner
- QUALIFIED: 已有行程方案，在考虑 → 回顾行程 + 挖掘顾虑
- NEGOTIATION: 谈价格/调整内容 → 处理异议 + 适度优惠
- CLOSING: 明确要买 → 报价 + 订单 + 支付链接
- WON: 已支付 → 确认 + 后续流程
- LOST: 7 天未转化或明确拒绝 → 留台阶

核心设计：
- 分阶段 Prompt 动态加载
- 旅程修改检测（goto_planner）→ 允许在销售中跳到 trip_planner 修改行程
- 跟进策略：24h 温和 → 3d 优惠 → 7d 放弃
- LLM 自然判定意向，不再用关键词硬匹配
"""

import re
import logging
from datetime import datetime, timedelta, timezone

from agents.base import BaseAgent
from graph.state import AgentState
from tools.mcp_tools import (
    load_trip_draft,
    quote_price,
    create_order,
    get_payment_url,
    apply_coupon,
    check_order_status,
    process_payment,
)
from services.llm import get_light_llm
from prompts import load_prompt

logger = logging.getLogger(__name__)

# =============================================================================
# Pipeline 阶段常量
# =============================================================================

STAGE_LEAD = "lead"
STAGE_QUALIFIED = "qualified"
STAGE_NEGOTIATION = "negotiation"
STAGE_CLOSING = "closing"
STAGE_WON = "won"
STAGE_LOST = "lost"

# 行程修改触发词
_TRIP_MODIFY_PATTERNS = [
    r"改.*(?:行程|方案|安排|路线|景点)",
    r"(?:调整|修改|换|换一下|换一换).*(?:行程|方案|安排|路线|景点|酒店|天数)",
    r"(?:换个|换一个|调整一下)(?:景点|酒店|路线|日期|天数)",
    r"(?:不想|不要|不喜欢).*(?:这个|那个|这里|那里|景点|酒店|地方|去)",
    r"(?:能不能|可以|可否).*(?:改|调整|换|修改)",
    r"(?:再加上|去掉|删除|增加|添加).*(?:景点|活动|项目|酒店|天)",
    r"(?:重新|再).*(?:设计|规划|安排|做|弄)",
    r"(?:想|想要|希望).*(?:换|改|调整|去掉|删除|增加).*(?:景点|酒店|行程|路线)",
]

# 强购买信号
_STRONG_BUY_SIGNALS = [
    "我要预订", "我要购买", "怎么付款", "帮我下单", "就这个",
    "我要支付", "确认预订", "锁定", "下单", "付定金",
    "现在买", "马上订", "立刻订", "给我订",
]

# 明确拒绝信号
_CLEAR_REJECTION = [
    "不需要了", "不买了", "放弃", "算了不", "太贵了不",
    "以后再说", "不想买", "不感兴趣", "别再问了",
]


def _detect_trip_modification(text: str) -> bool:
    """检测用户是否想要修改行程方案"""
    for pattern in _TRIP_MODIFY_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _detect_strong_buy(text: str) -> bool:
    """检测强购买信号（直接进入 CLOSING）"""
    for signal in _STRONG_BUY_SIGNALS:
        if signal in text:
            return True
    return False


def _detect_clear_rejection(text: str) -> bool:
    """检测明确拒绝信号"""
    for signal in _CLEAR_REJECTION:
        if signal in text:
            return True
    return False


def _determine_next_stage(
    current_stage: str, user_msg: str, llm_reply: str, has_draft: bool,
    tool_results: dict | None = None,
) -> str:
    """根据用户消息、LLM 回复和工具调用结果判定阶段转换

    规则优先级（代码判定为主，LLM 辅助）：
    1. process_payment 调用成功 → WON
    2. 明确拒绝 → LOST
    3. 强购买信号 → CLOSING
    4. 有 draft 且当前 LEAD → QUALIFIED
    5. 谈价格/优惠 → NEGOTIATION
    6. 订单创建成功 → WON
    """
    tool_results = tool_results or {}

    # process_payment 调用成功 → WON（最高优先级）
    if "process_payment" in tool_results:
        pr_result = tool_results["process_payment"]
        if "支付成功" in str(pr_result):
            return STAGE_WON

    # 明确拒绝 → LOST
    if _detect_clear_rejection(user_msg):
        return STAGE_LOST

    # 强购买信号 → CLOSING
    if _detect_strong_buy(user_msg):
        return STAGE_CLOSING

    # 支付成功关键词 → WON（v4.1: 仅支付成功触发 WON，订单创建不再触发）
    if "支付成功" in llm_reply or "付款成功" in llm_reply or "已到账" in llm_reply:
        return STAGE_WON

    # 有 draft 但还在 LEAD → 升级到 QUALIFIED
    if current_stage == STAGE_LEAD and has_draft:
        return STAGE_QUALIFIED

    # 价格/优惠讨论 → NEGOTIATION
    price_signals = ["价格", "费用", "贵", "便宜", "优惠", "折扣", "预算", "报价"]
    if any(s in user_msg for s in price_signals):
        if current_stage in (STAGE_LEAD, STAGE_QUALIFIED):
            return STAGE_NEGOTIATION

    # 保持当前阶段
    return current_stage


def _build_draft_context(state: AgentState) -> dict | None:
    """从 State 中提取行程方案上下文（用于注入 Prompt）

    优先使用 state.draft/need，其次从对话历史中正则提取。
    """
    need = state.get("need", {}) or {}
    draft = state.get("draft", {}) or {}

    # 如果有 draft 内容，优先用 draft
    if draft.get("itinerary_md"):
        return {
            "destination": need.get("destination", ""),
            "days": need.get("days", 0),
            "pax": need.get("pax", 0),
            "budget": need.get("budget", ""),
            "theme": need.get("theme", ""),
            "pace": need.get("pace", ""),
            "itinerary_summary": draft.get("itinerary_md", "")[:1000],
            "estimated_cost": draft.get("estimated_cost", ""),
        }

    # 仅有 need 无 draft
    if need.get("destination"):
        return {
            "destination": need.get("destination", ""),
            "days": need.get("days", 0),
            "pax": need.get("pax", 0),
            "budget": need.get("budget", ""),
            "theme": need.get("theme", ""),
            "pace": need.get("pace", ""),
        }

    # 无正式 need/draft → 从最近对话中正则提取（避免 LEAD 阶段反复询问已提供的城市）
    from langchain_core.messages import HumanMessage
    messages = state.get("messages", []) or []
    user_msgs = [m for m in messages if isinstance(m, HumanMessage)]
    # 合并最近 5 条用户消息的内容
    combined = " ".join(
        m.content for m in reversed(user_msgs[-5:])
        if hasattr(m, "content") and m.content
    )
    if combined:
        extracted: dict = {}
        cities = ["北京", "西安", "上海", "成都", "广州", "桂林", "杭州", "重庆",
                   "昆明", "拉萨", "哈尔滨", "三亚", "深圳", "南京", "武汉", "苏州",
                   "厦门", "大理", "丽江", "张家界"]
        for city in cities:
            if city in combined:
                extracted["destination"] = city
                break
        # 清洗日期模式后提取天数（避免 "9月20日" 被误提取为 20 天）
        cleaned = re.sub(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?', '', combined)
        cleaned = re.sub(r'\d{1,2}\s*月\s*\d{1,2}\s*[日号]', '', cleaned)
        m = re.search(r'(\d+)\s*[天日]', cleaned)
        if m and int(m.group(1)) <= 30:
            extracted["days"] = int(m.group(1))
        m = re.search(r'(\d+)\s*[人个位]', combined)
        if m:
            extracted["pax"] = int(m.group(1))
        m = re.search(r'[¥\$]\s*(\d[\d,]*)', combined)
        if m:
            extracted["budget"] = f"¥{m.group(1)}"
        if extracted.get("destination"):
            return extracted

    return None


def _load_draft_from_handoff(handoff: dict, state: AgentState) -> dict | None:
    """从交接上下文中加载行程草稿信息。

    优先使用 handoff_context 中的字段，其次从 State 提取，
    最后尝试从 MySQL 加载。
    """
    dest = handoff.get("destination", "")
    days = handoff.get("days", 0)
    pax = handoff.get("pax", 0)
    budget = handoff.get("budget", "")
    theme = handoff.get("theme", "")

    # 如果有 itinerary_md 直接用
    itinerary_md = handoff.get("itinerary_md", "")
    draft_id = handoff.get("draft_id", "")

    if dest and days:
        return {
            "destination": dest,
            "days": days,
            "pax": pax,
            "budget": budget,
            "theme": theme,
            "itinerary_summary": itinerary_md[:1000] if itinerary_md else f"{dest}{days}日游",
            "draft_id": draft_id,
        }

    # 回退到 State 提取
    ctx = _build_draft_context(state)
    if ctx:
        ctx["draft_id"] = draft_id or state.get("session_id", "")
        return ctx

    return None


# =============================================================================
# SalesAgent
# =============================================================================


class SalesAgent(BaseAgent):
    """销售顾问——Pipeline 驱动的分阶段销售"""

    def __init__(self):
        llm = get_light_llm()
        tools = [
            load_trip_draft,
            quote_price,
            create_order,
            get_payment_url,
            apply_coupon,
            check_order_status,
            process_payment,
        ]
        # 初始 prompt 用 LEAD，run() 中会根据实际阶段切换
        system_prompt = load_prompt("sales_lead.txt")
        super().__init__(llm=llm, tools=tools, system_prompt=system_prompt)

    async def run(self, state: AgentState) -> dict:
        user_msg = self._get_user_message(state)
        language = self._get_language(state)
        customer_id = state.get("customer_id", "unknown")
        session_id = state.get("session_id", "")

        # ── 第 0 步：检查交接上下文（v4: 从 trip_planner / ops 交接过来了）──
        handoff = self._get_handoff_context(state)
        handoff_reason = handoff.get("reason", "")
        is_handoff = bool(handoff_reason)

        if handoff_reason == "draft_confirmed":
            # 从 trip_planner 交接：客户刚确认了行程 → 跳过 LEAD
            draft_ctx = _load_draft_from_handoff(handoff, state)
            has_draft = True
            pipeline = {
                "stage": STAGE_QUALIFIED, "followup_count": 0,
                "discount_offered": False,
            }
            # 创建 pipeline 记录
            try:
                from services.memory import MemoryManager
                mm = MemoryManager()
                await mm.upsert_pipeline(customer_id, {
                    "stage": STAGE_QUALIFIED,
                    "draft_id": handoff.get("draft_id", session_id),
                    "destination": draft_ctx.get("destination", "") if draft_ctx else "",
                    "days": draft_ctx.get("days") if draft_ctx else None,
                    "pax": draft_ctx.get("pax") if draft_ctx else None,
                    "budget": draft_ctx.get("budget", "") if draft_ctx else "",
                })
            except Exception as e:
                logger.warning("Failed to create pipeline from handoff: %s", e)
        elif handoff_reason == "re_purchase_request":
            # 从 ops 交接：用户想加购 → 有行程 + 有订单
            draft_ctx = _load_draft_from_handoff(handoff, state)
            has_draft = True
            pipeline = {
                "stage": STAGE_QUALIFIED, "followup_count": 0,
                "discount_offered": False,
            }
        else:
            # 正常流程
            draft_ctx = _build_draft_context(state)
            has_draft = draft_ctx is not None
            pipeline = await self._load_pipeline(customer_id, state, draft_ctx)

        current_stage = pipeline.get("stage", STAGE_LEAD)
        has_unconverted = state.get("has_unconverted_trip", False)

        # ── 第 2 步：跟进处理 ──
        followup_msg = ""
        if has_unconverted and current_stage != STAGE_LOST:
            followup_msg = self._build_followup_message(pipeline, draft_ctx)
            if followup_msg:
                current_stage = pipeline["stage"]  # 可能已被 followup 逻辑更新

        # ── 第 3 步：动态选 Prompt ──
        self.system_prompt = self._load_stage_prompt(current_stage, draft_ctx)

        # ── 第 4 步：构建 extra_context ──
        extra_context = self._build_extra_context(state, draft_ctx, pipeline, followup_msg)

        # ── 第 5 步：空消息兜底 ──
        if not user_msg:
            return self._empty_reply(current_stage, has_draft, followup_msg)

        # ── 第 6 步：LLM + Tool Calling ──
        # 提取对话历史（最近 5 轮，不含当前消息），让 LLM 记住上下文
        history = self._get_message_history(state, max_turns=5)
        loop_result = await self._run_tool_calling_loop(
            user_msg, language=language, extra_context=extra_context,
            session_id=session_id, history=history,
        )
        final_text = loop_result["final_text"]
        need_human = loop_result["need_human"]

        # ── 第 7 步：阶段转换判定 ──
        new_stage = _determine_next_stage(
            current_stage, user_msg, final_text, has_draft,
            tool_results=loop_result.get("tool_results", {}),
        )

        # ── 第 8 步：检测行程修改 ──
        goto_planner = _detect_trip_modification(user_msg)

        # ── 第 9 步：投诉检测 ──
        complaint_keywords = ["投诉", "退款", "骗人", "诈骗", "差评"]
        for kw in complaint_keywords:
            if kw in user_msg:
                need_human = True
                break

        # ── 第 10 步：保存 Pipeline 状态 ──
        try:
            from services.memory import MemoryManager
            mm = MemoryManager()
            if new_stage == STAGE_WON:
                await mm.mark_pipeline_won(customer_id)
            elif new_stage == STAGE_LOST:
                await mm.mark_pipeline_lost(customer_id)
            else:
                await mm.upsert_pipeline(customer_id, {
                    "stage": new_stage,
                    "draft_id": session_id,
                    "destination": draft_ctx.get("destination", "") if draft_ctx else "",
                    "days": draft_ctx.get("days") if draft_ctx else None,
                    "pax": draft_ctx.get("pax") if draft_ctx else None,
                    "budget": draft_ctx.get("budget", "") if draft_ctx else "",
                })
        except Exception as e:
            logger.warning("Failed to save pipeline: %s", e)

        # ── 第 11 步：构建返回（v4: 含 journey_stage + next_agent）──
        quote_text = ""
        if "报价" in final_text or "费用" in final_text:
            quote_text = final_text[:500]

        # 确定交接字段
        if new_stage == STAGE_WON:
            journey_stage = "post_purchase"
            next_agent = "operations_agent"
            hc = {
                "reason": "payment_completed",
                "from_agent": "sales_agent",
                "order_summary": f"{draft_ctx.get('destination', '')}{draft_ctx.get('days', '')}天" if draft_ctx else "",
            }
            # 尝试从工具结果提取订单号
            import re as _re
            for tool_name in ["process_payment", "create_order"]:
                tr = loop_result.get("tool_results", {}).get(tool_name, "")
                if tr:
                    order_match = _re.search(r'ORD-[\w-]+', str(tr))
                    if order_match:
                        hc["order_id"] = order_match.group(0)
                        break
            # 回退到从 final_text 提取
            if not hc.get("order_id"):
                order_match = _re.search(r'ORD-[\w-]+', final_text)
                if order_match:
                    hc["order_id"] = order_match.group(0)
        elif goto_planner:
            journey_stage = "planning"
            next_agent = "trip_planner"
            hc = {
                "reason": "trip_modify_requested",
                "from_agent": "sales_agent",
                "draft_summary": (draft_ctx.get("itinerary_summary", "") if draft_ctx else ""),
                "draft_id": session_id,
            }
        elif new_stage == STAGE_LOST:
            journey_stage = "discovery"
            next_agent = ""
            hc = {}
        else:
            journey_stage = "sales"
            next_agent = "sales_agent"
            hc = {}

        return self._build_response(
            final_reply=final_text,
            journey_stage=journey_stage,
            next_agent=next_agent,
            handoff_context=hc,
            need_human=need_human,
            intent_level=self._stage_to_intent(new_stage),
            next_action=self._stage_to_action(new_stage),
            current_branch="sales_agent",
            quote=quote_text,
            sales_pipeline_stage=new_stage,
            goto_planner=goto_planner,
            has_unconverted_trip=has_unconverted,
        )

    # =========================================================================
    # Pipeline 加载
    # =========================================================================

    async def _load_pipeline(
        self, customer_id: str, state: AgentState, draft_ctx: dict | None,
    ) -> dict:
        """从 DB 加载或创建新的 pipeline 记录"""
        try:
            from services.memory import MemoryManager
            mm = MemoryManager()
            pipeline = await mm.get_active_pipeline(customer_id)
            if pipeline:
                self._check_followup_timers(pipeline)
                return pipeline
        except Exception as e:
            logger.debug("Failed to load pipeline from DB: %s", e)

        # 默认：根据是否有 draft 判断初始阶段
        has_draft = draft_ctx is not None
        default_stage = STAGE_QUALIFIED if has_draft else STAGE_LEAD
        return {"stage": default_stage, "followup_count": 0, "discount_offered": False}

    def _check_followup_timers(self, pipeline: dict) -> None:
        """检查跟进时间窗口并更新阶段（纯内存操作，不写 DB）

        24h 不活跃 → 标记需要温和追问
        3d 不活跃 + 未给过优惠 → 标记需要优惠跟进
        7d 不活跃 → 标记 LOST
        """
        updated_at = pipeline.get("updated_at", "")
        if not updated_at:
            return

        try:
            last_time = datetime.fromisoformat(updated_at)
            now = datetime.now(timezone.utc)
            gap = now - last_time.replace(tzinfo=timezone.utc) if last_time.tzinfo is None else now - last_time
            gap_hours = gap.total_seconds() / 3600

            if gap_hours >= 7 * 24:
                pipeline["_auto_lost"] = True
            elif gap_hours >= 3 * 24 and not pipeline.get("discount_offered"):
                pipeline["_offer_discount"] = True
            elif gap_hours >= 24:
                pipeline["_gentle_nudge"] = True
        except (ValueError, TypeError):
            pass

    # =========================================================================
    # 跟进消息
    # =========================================================================

    def _build_followup_message(
        self, pipeline: dict, draft_ctx: dict | None,
    ) -> str:
        """根据跟进阶段生成开场白"""
        dest = ""
        days = ""
        if draft_ctx:
            dest = draft_ctx.get("destination", "")
            days = f"{draft_ctx.get('days', '')}天" if draft_ctx.get("days") else ""

        trip_desc = f"{dest}{days}" if dest else "行程"

        if pipeline.get("_auto_lost"):
            pipeline["stage"] = STAGE_LOST
            return ""

        if pipeline.get("_offer_discount"):
            pipeline["stage"] = STAGE_NEGOTIATION
            pipeline["discount_offered"] = True
            return (
                f"【系统提示】客户 {trip_desc} 的行程方案已闲置 3 天以上。"
                f"在对话中自然地向客户提及：'好久不见！您的{trip_desc}行程方案我还为您保留着"
                f"——现在预订的话，我可以为您申请一个专属优惠~'"
                f"如果客户有兴趣，使用 apply_coupon 工具发放优惠券。"
            )

        if pipeline.get("_gentle_nudge"):
            return (
                f"【系统提示】客户之前有 {trip_desc} 的行程方案但未下单（超过24小时）。"
                f"在开场白中温和地提及：'欢迎回来！您的{trip_desc}行程方案还在，"
                f"有需要我帮您继续推进的吗？'"
            )

        return ""

    # =========================================================================
    # Prompt 选择
    # =========================================================================

    def _load_stage_prompt(self, stage: str, draft_ctx: dict | None) -> str:
        """根据 pipeline 阶段加载对应的 prompt"""
        prompt_name = f"sales_{stage}.txt"
        try:
            prompt = load_prompt(prompt_name)
        except Exception:
            logger.warning("Prompt '%s' not found, falling back to sales_lead.txt", prompt_name)
            prompt = load_prompt("sales_lead.txt")

        # 如果有行程上下文，追加到 prompt
        if draft_ctx:
            ctx_lines = [
                "\n\n## 客户行程信息\n",
                f"- 目的地：{draft_ctx.get('destination', '未知')}",
                f"- 天数：{draft_ctx.get('days', '未知')} 天",
                f"- 人数：{draft_ctx.get('pax', '未知')} 人",
                f"- 预算：{draft_ctx.get('budget', '未设置')}",
            ]
            if draft_ctx.get("theme"):
                ctx_lines.append(f"- 偏好主题：{draft_ctx['theme']}")
            if draft_ctx.get("pace"):
                ctx_lines.append(f"- 节奏偏好：{draft_ctx['pace']}")
            if draft_ctx.get("estimated_cost"):
                ctx_lines.append(f"- 预估费用：{draft_ctx['estimated_cost']}")
            if draft_ctx.get("itinerary_summary"):
                ctx_lines.append(f"\n### 行程概要\n{draft_ctx['itinerary_summary']}")

            prompt += "\n".join(ctx_lines)

        return prompt

    def _build_extra_context(
        self, state: AgentState, draft_ctx: dict | None,
        pipeline: dict, followup_msg: str,
    ) -> dict | None:
        """构建传给 LLM 的附加上下文"""
        ctx = {}

        # 用户画像
        profile = state.get("user_profile", {}) or {}
        if profile.get("nationality"):
            ctx["客户国籍"] = profile["nationality"]
        if profile.get("budget_range"):
            br = profile["budget_range"]
            if isinstance(br, dict):
                ctx["预算范围"] = f"{br.get('min','')}-{br.get('max','')} {br.get('currency','')}"
            else:
                ctx["预算范围"] = str(br)

        # 偏好信息
        prefs = state.get("user_preferences", {}) or {}
        if prefs.get("preferred_destinations"):
            ctx["偏好目的地"] = ", ".join(prefs["preferred_destinations"])
        if prefs.get("travel_style"):
            ctx["旅行风格"] = prefs["travel_style"]

        # 当前 Pipeline 阶段
        ctx["当前销售阶段"] = pipeline.get("stage", STAGE_LEAD)

        # 跟进指令
        if followup_msg:
            ctx["跟进指令"] = followup_msg

        return ctx if ctx else None

    # =========================================================================
    # 空消息兜底
    # =========================================================================

    def _empty_reply(self, stage: str, has_draft: bool, followup_msg: str) -> dict:
        """无用户消息时的兜底回复"""
        if followup_msg:
            return self._build_response(
                final_reply="欢迎回来！有什么旅行相关的问题需要我协助吗？",
                journey_stage="sales",
                next_agent="sales_agent",
                current_branch="sales_agent",
                sales_pipeline_stage=stage,
                goto_planner=False,
                intent_level=self._stage_to_intent(stage),
                next_action=self._stage_to_action(stage),
            )

        if stage == STAGE_LEAD:
            text = "您好！我是您的专属旅行顾问。想去哪里旅行？我帮您规划最合适的方案！"
        elif has_draft:
            text = "您好！我是您的旅行顾问。之前的行程方案您看过了吗？有什么需要调整或确认的吗？"
        else:
            text = "您好！有什么旅行相关的需求需要我协助吗？"

        return self._build_response(
            final_reply=text,
            journey_stage="sales",
            next_agent="sales_agent",
            current_branch="sales_agent",
            sales_pipeline_stage=stage,
            goto_planner=False,
            intent_level=self._stage_to_intent(stage),
            next_action=self._stage_to_action(stage),
        )

    # =========================================================================
    # 阶段 → 意向/动作 映射
    # =========================================================================

    @staticmethod
    def _stage_to_intent(stage: str) -> str:
        if stage == STAGE_CLOSING or stage == STAGE_WON:
            return "high"
        if stage == STAGE_LOST:
            return "low"
        if stage == STAGE_NEGOTIATION:
            return "high"
        return "mid"

    @staticmethod
    def _stage_to_action(stage: str) -> str:
        if stage in (STAGE_CLOSING, STAGE_WON):
            return "accept"
        if stage == STAGE_LOST:
            return "give_up"
        return "revise"


# =============================================================================
# 模块级单例
# =============================================================================

_agent_instance: SalesAgent | None = None


def get_sales_agent() -> SalesAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SalesAgent()
    return _agent_instance
