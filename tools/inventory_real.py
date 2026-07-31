"""真实库存 API——预留接口

需要对接：
- 酒店 PMS/CRS 系统（如 Opera、Mews）获取实时房态和价格
- 景区票务系统（如 Trip.com / Klook API）获取门票库存
- 车辆调度系统获取包车/拼车可用性

实现方式：继承 BaseInventoryBackend 并实现 query() 方法。

当前骨架直接 raise NotImplementedError。
"""


def query_inventory_real(city: str, date: str, pax: int) -> str:
    """真实库存查询——待对接外部系统。

    Args:
        city: 城市名称
        date: 到达日期
        pax: 人数

    Raises:
        NotImplementedError: 尚未实现真实库存对接
    """
    raise NotImplementedError(
        "真实库存 API 尚未对接。\n\n"
        "需要对接以下系统：\n"
        "1. 酒店 PMS/CRS —— 实时房态、价格、可预订量\n"
        "2. 景区票务 —— 电子票库存、时段预约\n"
        "3. 车辆调度 —— 包车/拼车可用性\n\n"
        f"查询参数：city={city}, date={date}, pax={pax}"
    )
