"""SSE 流式桥接——Agent 与 SSE 端点之间的 token 传递通道

在 LangGraph 中，节点函数是同步/异步执行的，无法直接向 SSE 端点 yield。
通过 asyncio.Queue 桥接：Agent 在生产 token 时 push 到队列，
SSE 端点从队列中读取并发送给前端。

使用方式：
    # Agent 内部
    from services.stream_bridge import push_token, push_node_event
    push_token(session_id, "你好")

    # SSE 端点
    from services.stream_bridge import create_queue, remove_queue
    queue = create_queue(session_id)
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# 全局注册表：conversation_id → asyncio.Queue
_token_queues: dict[str, asyncio.Queue] = {}

# 队列最大容量（防止内存泄漏）
_MAX_QUEUE_SIZE = 4096


def create_queue(session_id: str) -> asyncio.Queue:
    """为指定会话创建 token 队列。

    在 SSE 端点开始时调用。如果该会话已有队列，先清理旧的。
    """
    old = _token_queues.pop(session_id, None)
    if old is not None:
        # 清空旧队列
        while not old.empty():
            try:
                old.get_nowait()
            except asyncio.QueueEmpty:
                break
    q = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
    _token_queues[session_id] = q
    logger.debug("Stream queue created for session %s", session_id)
    return q


def remove_queue(session_id: str):
    """移除并清理指定会话的 token 队列。

    在 SSE 端点完成/异常时调用。
    """
    q = _token_queues.pop(session_id, None)
    if q is not None:
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.debug("Stream queue removed for session %s", session_id)


def push_token(session_id: str, text: str):
    """Agent 调用：向 SSE stream 推送一个文本 token。

    如果该会话没有活跃的 stream 队列（非流式调用），静默忽略。

    Args:
        session_id: 对话 ID（对应 AgentState.session_id）
        text: 要推送的文本片段（通常是一个或几个字符）
    """
    q = _token_queues.get(session_id)
    if q is None:
        return  # 非流式调用，忽略
    try:
        q.put_nowait(("token", text))
    except asyncio.QueueFull:
        logger.warning("Stream queue full for session %s, dropping token", session_id)


def push_node_event(session_id: str, node_name: str, label: str):
    """推送图节点进度事件（node_start + node_complete）。

    在 SSE 端点中，LangGraph astream 循环之外也可以调用此函数。
    """
    q = _token_queues.get(session_id)
    if q is None:
        return
    try:
        q.put_nowait(("node_start", {"node": node_name, "label": label}))
        q.put_nowait(("node_complete", {"node": node_name}))
    except asyncio.QueueFull:
        pass


def push_done(session_id: str, final_state: dict):
    """推送流完成事件。"""
    q = _token_queues.get(session_id)
    if q is None:
        return
    try:
        q.put_nowait(("done", final_state))
    except asyncio.QueueFull:
        logger.warning("Stream queue full for session %s, cannot push done", session_id)


def push_error(session_id: str, message: str):
    """推送错误事件。"""
    q = _token_queues.get(session_id)
    if q is None:
        return
    try:
        q.put_nowait(("error", message))
    except asyncio.QueueFull:
        pass
