"""真实报价 API——预留接口

需要对接：
- 内部定价引擎（价格规则、成本计算）
- 供应商报价系统（酒店/交通/门票批发价）
- 汇率 API（如 exchangerate.host）获取实时汇率

实现方式：继承 BaseQuoteBackend 并实现 generate() 方法。

当前骨架直接 raise NotImplementedError。
"""


def quote_price_real(
    destination: str,
    days: int,
    pax: int,
    budget: str = "",
    theme: str = "",
    pace: str = "",
) -> str:
    """真实报价——待对接定价系统。

    Args:
        destination: 目的地城市
        days: 行程天数
        pax: 人数
        budget: 预算（可选，如 "$2000"、"3000 RMB"）
        theme: 偏好主题
        pace: 节奏偏好

    Raises:
        NotImplementedError: 尚未实现真实报价对接
    """
    raise NotImplementedError(
        "真实报价引擎尚未对接。\n\n"
        "需要对接以下系统：\n"
        "1. 内部定价规则引擎 —— 成本计算、利润率配置\n"
        "2. 供应商报价系统 —— 酒店/交通/门票批发价\n"
        "3. 实时汇率 API —— 多币种报价\n\n"
        f"查询参数：destination={destination}, days={days}, pax={pax}"
    )
