"""修订计数器

每次修订时 revision_count +1，然后回到 trip_planner 重新生成。
硬上限 3 次，超过后由 revision_decision 转入 human_handoff。
"""

from graph.state import AgentState


def revision_loop(state: AgentState) -> dict:
    """修订计数 +1

    在 trip_planner 重新生成之前调用，确保每次修订都会被追踪。

    Args:
        state: 当前 AgentState

    Returns:
        dict 包含 revision_count 增量
    """
    current = state.get("revision_count", 0)
    return {"revision_count": current + 1}
