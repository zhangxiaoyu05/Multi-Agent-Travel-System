"""Agent 基类——统一 LLM + Tools 的调用模式

所有业务 Agent 继承此类，遵循：
- __init__ 接收 llm、tools、system_prompt
- run(state) → dict 返回要合并到 AgentState 的字段

这样每个 Agent 只需要关心自己的业务逻辑，不用关心图结构。
"""

from abc import ABC, abstractmethod
from langchain_openai import ChatOpenAI
from graph.state import AgentState


class BaseAgent(ABC):
    """所有业务 Agent 的基类"""

    def __init__(self, llm: ChatOpenAI, tools: list, system_prompt: str):
        """
        Args:
            llm: ChatOpenAI 实例（由 services.llm 工厂创建）
            tools: LangChain Tool 列表，Agent 可调用
            system_prompt: 系统提示词字符串
        """
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt

    @abstractmethod
    def run(self, state: AgentState) -> dict:
        """执行 Agent 逻辑，返回要合并到 AgentState 的 dict

        典型返回：
            {
                "final_reply": "生成的回复文本",
                "need_human": False,
                "need": {...}     # 可选，业务数据
            }
        """
        ...

    def _get_user_message(self, state: AgentState) -> str:
        """从 State 中提取最后一条用户消息文本"""
        messages = state.get("messages", [])
        if not messages:
            return ""
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)

    def _get_message_history(self, state: AgentState, max_turns: int = 3) -> list:
        """提取最近的对话历史（最近 max_turns 轮）

        Args:
            state: 当前 AgentState
            max_turns: 最多返回的轮数

        Returns:
            LangChain 消息列表
        """
        messages = state.get("messages", [])
        # 每轮 = user + assistant，取最后 2*max_turns 条
        return list(messages[-(max_turns * 2):])
