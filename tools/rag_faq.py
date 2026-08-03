"""RAG FAQ 搜索工具——双路检索 + RRF 融合

在线检索流程：
    用户问题 → 向量化 → 双路并行检索
        ├── Path A: Milvus/JSON 向量语义检索（余弦相似度）
        └── Path B: BM25 关键词检索（中英文混合分词）
    → RRF 倒数排名融合 → Top-K → 返回格式化的知识库内容

离线入库流程保持不变：scripts/ingest_knowledge.py 摄入到 Milvus/JSON。

三层回退策略（仅在所有检索路径都失败时触发）：
    1. 双路 + RRF 融合（主路径）
    2. 关键词兜底匹配（Milvus + BM25 均不可用）
    3. 通用回退消息

使用方式：
    from tools.rag_faq import search_faq
    result = search_faq.invoke({"query": "签证需要什么材料？"})
"""

import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# =============================================================================
# 关键词兜底库（所有检索路径都不可用时的 fallback）
# =============================================================================

_FALLBACK_FAQ: dict[str, str] = {
    "签证材料": (
        "【签证政策】\n"
        "中国旅游签证（L签）基本材料：\n"
        "1. 有效期6个月以上的护照\n"
        "2. 签证申请表\n"
        "3. 近期2寸白底照片\n"
        "4. 往返机票订单\n"
        "5. 酒店预订确认\n"
        "6. 行程安排\n"
        "7. 部分国家需提供邀请函\n\n"
        "中国对部分国家实行144小时过境免签政策，覆盖北京、上海、广州、西安等主要城市。"
    ),
    "支付": (
        "【支付方式】\n"
        "在中国旅行推荐：微信支付（WeChat Pay）、支付宝（Alipay），两者均支持境外银行卡绑定。\n"
        "Visa/Mastercard 信用卡在大型酒店和商场可用。\n"
        "建议：出发前绑定国际信用卡到微信或支付宝，可大幅提升支付便利性。"
    ),
    "退改": (
        "【退改政策】\n"
        "- 出发前7天以上取消：全额退款（扣除少量手续费）\n"
        "- 出发前3-7天取消：收取50%费用\n"
        "- 出发前3天内取消：收取100%费用\n"
        "- 因不可抗力（自然灾害、疫情等）取消：可申请全额退款。"
    ),
    "天气": (
        "【天气概况】\n"
        "中国地域辽阔，各地气候差异显著。北京夏季25-35°C、冬季-10~5°C；"
        "西安夏季25-38°C；上海夏季25-35°C（潮湿）；成都四季温和多雨雾。\n"
        "建议出发前3天查询目的地具体天气预报。"
    ),
    "小费": (
        "【小费文化】\n"
        "中国大陆不实行小费制度。酒店行李员可酌情给5-10元人民币。\n"
        "部分高档餐厅可能收取10-15%服务费（会在账单中标注）。"
    ),
    "网络": (
        "【网络与上网】\n"
        "推荐：购买本地SIM卡、租用便携WiFi或开通国际漫游。\n"
        "注意：Google、Facebook等在中国无法直接访问，建议提前安装VPN。\n"
        "推荐下载WeChat作为主要通讯工具。"
    ),
    "交通": (
        "【交通出行】\n"
        "高铁覆盖全国主要城市（300km/h+）；地铁覆盖一线城市（票价2-10元）；"
        "滴滴出行（Didi）支持英文界面和境外信用卡。\n"
        "建议下载：12306（火车票）、滴滴出行、高德地图。"
    ),
    "安全": (
        "【安全提示】\n"
        "中国是世界上最安全的旅游目的地之一，暴力犯罪率极低。\n"
        "注意保管财物、去正规银行换汇。紧急电话：110（报警）、120（急救）、119（火警）。\n"
        "建议购买旅行保险，覆盖医疗和财物损失。"
    ),
    "美食": (
        "【美食推荐】\n"
        "北京烤鸭、西安肉夹馍/羊肉泡馍、上海小笼包/生煎、成都火锅/麻婆豆腐、广州早茶点心。\n"
        "建议尝试当地小吃街/夜市，体验最地道的美食文化。"
    ),
    "语言": (
        "【语言沟通】\n"
        "主要城市酒店、机场基本有英文服务。小商铺、出租车可能只讲中文。\n"
        "推荐：Google Translate（拍照翻译）、有道翻译。\n"
        "准备酒店名片（中文地址），打车时出示给司机。"
    ),
    "健康": (
        "【健康提示】\n"
        "出行前建议：购买旅游保险（含医疗）、携带常用药品、注意饮食卫生喝瓶装水。\n"
        "中国医疗资源丰富，大城市均有国际医院。紧急电话：120（急救）。"
    ),
}


# =============================================================================
# 工具定义
# =============================================================================


@tool
def search_faq(query: str) -> str:
    """搜索 FAQ 知识库回答用户关于旅游（签证、支付、天气、安全等）的常见问题。

    采用双路检索 + RRF 融合策略：
    1. 向量语义检索（Milvus/JSON 余弦相似度）
    2. BM25 关键词检索
    3. RRF 倒数排名融合 → Top-K

    Args:
        query: 用户的中文问题

    Returns:
        格式化的 FAQ 回答文本，或提示无相关结果
    """
    if not query or not query.strip():
        return "请提供您想了解的具体问题，例如：签证需要什么材料？"

    # =========================================================================
    # 主路径：双路检索 + RRF 融合
    # =========================================================================
    fused = _dual_path_search(query, top_k=5)

    # 检查融合结果质量：最佳 RRF 得分需 >= 阈值，否则视为无匹配
    _MIN_RRF_SCORE = 0.015  # RRF 得分最低阈值（低于此值视为噪音）
    if fused and fused[0].get("score", 0) >= _MIN_RRF_SCORE:
        return _format_results(fused, query)

    # 融合结果质量不足 → 进入兜底

    # =========================================================================
    # 兜底路径：关键词匹配
    # =========================================================================
    for keyword, answer in _FALLBACK_FAQ.items():
        if keyword in query:
            return answer

    # 英文关键词映射
    fuzzy_map: dict[str, str] = {
        "visa": "签证材料", "payment": "支付", "cancel": "退改", "refund": "退改",
        "weather": "天气", "tip": "小费", "wifi": "网络", "internet": "网络",
        "transport": "交通", "taxi": "交通", "subway": "交通",
        "safety": "安全", "food": "美食", "eat": "美食", "restaurant": "美食",
        "language": "语言", "english": "语言", "health": "健康", "hospital": "健康",
    }
    query_lower = query.lower()
    for en_key, cn_key in fuzzy_map.items():
        if en_key in query_lower:
            return _FALLBACK_FAQ.get(cn_key, "")

    # =========================================================================
    # 最终兜底
    # =========================================================================
    return (
        "感谢您的咨询！这个问题我需要更多信息才能准确回答。\n\n"
        "您可以尝试以下方式：\n"
        "1. 更具体地描述您的问题（例如: 签证需要什么材料?）\n"
        "2. 输入「人工」转接人工客服\n"
        "3. 常见问题类别：签证、支付、退改、天气、交通、网络、美食、安全、语言、健康"
    )


# =============================================================================
# 双路检索核心逻辑
# =============================================================================


def _dual_path_search(query: str, top_k: int = 5) -> list[dict]:
    """执行双路检索 + RRF 融合。

    Path A: Milvus/JSON 向量语义检索
    Path B: BM25 关键词检索
    两路并行，结果经 RRF 融合后返回 Top-K。

    Args:
        query:  用户查询
        top_k:  返回结果数

    Returns:
        RRF 融合后的 Top-K 文档列表，或空列表
    """
    vector_results: list[dict] = []
    bm25_results: list[dict] = []

    # ---- Path A: 向量检索 ----
    try:
        from services.vector_store import search_knowledge
        vector_results = search_knowledge(query, top_k=top_k * 2, score_threshold=0.3)
        for r in vector_results:
            r["source"] = "vector"
    except Exception as e:
        logger.warning("Vector search unavailable: %s", e)

    # ---- Path B: BM25 关键词检索 ----
    try:
        from tools.bm25_retriever import get_bm25_retriever
        bm25 = get_bm25_retriever()
        if bm25.doc_count > 0:
            raw_bm25 = bm25.search(query, top_k=top_k * 2)
            # 自适应阈值：按查询 token 数归一化，过滤弱匹配噪音
            from tools.bm25_retriever import tokenize
            qt_count = max(len(tokenize(query)), 1)
            _BM25_MIN_PER_TOKEN = 0.5  # 每个 token 的最低 BM25 贡献
            bm25_results = [
                r for r in raw_bm25
                if r.get("score", 0) / qt_count >= _BM25_MIN_PER_TOKEN
            ]
    except Exception as e:
        logger.warning("BM25 search unavailable: %s", e)

    # ---- 如果两路都不可用，返回空 ----
    if not vector_results and not bm25_results:
        return []

    # ---- 如果只有一路有结果，直接返回该路 ----
    if vector_results and not bm25_results:
        return vector_results[:top_k]
    if bm25_results and not vector_results:
        return bm25_results[:top_k]

    # ---- RRF 融合 ----
    try:
        from tools.rrf_fusion import rrf_fuse_from_results
        fused = rrf_fuse_from_results(vector_results, bm25_results, top_k=top_k)
        if fused:
            logger.info(
                "RRF fused: vector=%d + bm25=%d → top-%d (sources=%s)",
                len(vector_results), len(bm25_results), len(fused),
                fused[0].get("sources", []) if fused else [],
            )
        return fused
    except Exception as e:
        logger.warning("RRF fusion failed, falling back to vector results: %s", e)
        return vector_results[:top_k]


# =============================================================================
# 结果格式化
# =============================================================================


def _format_results(results: list[dict], query: str) -> str:
    """将检索结果格式化为 LLM 可用的上下文文本。

    包含：
    - 每条结果的 category 标题
    - 内容原文
    - 来源标记（vector / bm25 / vector+bm25）

    Args:
        results: RRF 融合后的文档列表
        query:   原始用户问题（保留以便后续 prompt 使用）

    Returns:
        带格式的 Markdown 文本
    """
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        category = meta.get("category", "")
        city = meta.get("city", "")
        sources = r.get("sources", [])

        # 标题行：序号 + 分类 + 来源
        header_parts = [f"### 📄 参考资料 {i}"]
        if category:
            header_parts.append(f"【{category}】")
        if city:
            header_parts.append(f"({city})")
        if sources:
            source_str = "+".join(sources)
            header_parts.append(f"`[{source_str}]`")
        lines.append(" ".join(header_parts))

        # 内容
        content = r.get("content", "")
        lines.append(content)
        lines.append("")  # 空行分隔

    # 底部提示
    lines.append("---")
    lines.append(
        "*以上内容来自平台知识库，请基于这些信息组织回答。"
        "如果知识库内容不足以完全回答用户问题，请诚实地说明，不要编造信息。*"
    )

    return "\n".join(lines)
