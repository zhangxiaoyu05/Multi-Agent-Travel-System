"""Agent 基类——统一异步 LLM + Tools 调用模式

所有业务 Agent 继承此类，获得：
- 异步 invoke（await llm.ainvoke）
- 标准 tool-calling 循环（_run_tool_calling_loop）
- 消息提取工具方法

子类只需要：
1. 在 __init__ 中设置 llm、tools、system_prompt、_tool_executors
2. 实现 async run(state) → dict
"""

from abc import ABC, abstractmethod
from graph.state import AgentState
from services.llm import BailianLLM, LLMResponse
from prompts import get_language_instruction


class BaseAgent(ABC):
    """所有业务 Agent 的异步基类。

    内置标准 tool-calling 循环，子类可直接调用 _run_tool_calling_loop()。
    """

    def __init__(self, llm: BailianLLM, tools: list, system_prompt: str):
        """
        Args:
            llm: BailianLLM 实例（由 services.llm 工厂创建）
            tools: LangChain Tool 列表
            system_prompt: 系统提示词字符串
        """
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt

        # 子类可在 __init__ 中设置此映射来声明 tool 执行器
        # 格式: {"tool_name": callable}
        self._tool_executors: dict[str, callable] = {}

    # =========================================================================
    # 公共接口
    # =========================================================================

    @abstractmethod
    async def run(self, state: AgentState) -> dict:
        """执行 Agent 逻辑（异步），返回要合并到 AgentState 的 dict

        典型返回：
            {
                "final_reply": "生成的回复文本",
                "need_human": False,
                "intent_level": "mid",
                "next_action": "revise",
            }
        """
        ...

    # =========================================================================
    # 标准 tool-calling 循环（消除重复代码）
    # =========================================================================

    async def _run_tool_calling_loop(
        self, user_msg: str, language: str = "zh", extra_context: dict | None = None,
        session_id: str = "",
    ) -> dict:
        """标准 LLM + Tool 调用循环（支持流式输出到前端）。

        流程：
            1. LLM 决策（直接回复 or 调用 tools）
            2. 若有 tool_calls → 执行对应的 tool
            3. 将 tool 结果回传给 LLM 生成最终回复
               （若提供 session_id，最终回复使用流式输出逐 token 推送到前端）

        Args:
            user_msg: 用户消息文本
            language: 语言代码（zh/en/ja/ko），用于注入语言指令
            extra_context: 额外上下文，注入到 system prompt 后
            session_id: 会话 ID。若提供，最终回复将流式推送到前端

        Returns:
            {
                "final_text": str,         # 最终回复文本
                "need_human": bool,        # 是否需要转人工
                "tool_results": dict,      # {tool_name: result_string}
            }
        """
        if not user_msg:
            return {"final_text": "", "need_human": False, "tool_results": {}}

        # Step 1: 首次 LLM 调用（带 tools，始终非流式——需要完整的 tool_call 结构）
        system_content = self.system_prompt + get_language_instruction(language)
        if extra_context:
            ctx_str = "\n".join(f"{k}: {v}" for k, v in extra_context.items())
            system_content = f"{system_content}\n\n[附加上下文]\n{ctx_str}"

        llm_with_tools = self.llm.bind_tools(self.tools)
        response = await llm_with_tools.ainvoke([
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_msg},
        ])

        # Step 2: 执行 tool calls
        need_human = False
        tool_results: dict[str, str] = {}

        if response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("args", {})
                result = self._execute_tool(tool_name, tool_args)
                tool_results[tool_name] = result

                # check_handoff 语义：结果含"需要转人工" → 标记 need_human
                if tool_name == "check_handoff" and "需要转人工" in str(result):
                    need_human = True

        # Step 3: 生成最终回复（若 session_id 非空则流式输出）
        if response.tool_calls:
            tool_messages = []
            for tc in response.tool_calls:
                tool_name = tc["name"]
                if tool_name in tool_results:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_results[tool_name],
                    })

            if tool_messages:
                conversation = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_msg},
                    response.to_message_dict(),
                ] + tool_messages

                final_text = await self._stream_final(conversation, session_id)
                return {
                    "final_text": final_text,
                    "need_human": need_human,
                    "tool_results": tool_results,
                }

        # 没有工具调用：直接返回 LLM 回复（流式）
        final_text = response.content
        return {
            "final_text": final_text,
            "need_human": need_human,
            "tool_results": tool_results,
        }

    async def _stream_final(self, messages: list, session_id: str) -> str:
        """用流式方式生成最终回复，同时推送到前端。

        若 session_id 为空，退化为普通 ainvoke 调用。
        """
        if not session_id:
            response = await self.llm.ainvoke(messages)
            return response.content

        from services.stream_bridge import push_token
        full = ""
        async for chunk in self.llm.astream(messages):
            full += chunk
            push_token(session_id, chunk)
        return full

    def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """执行单个工具调用。

        优先使用 _tool_executors 注册的执行器，
        否则遍历 self.tools 查找匹配的 tool 并调用 .invoke()。
        """
        # 注册的执行器优先
        executor = self._tool_executors.get(tool_name)
        if executor is not None:
            return str(executor(tool_args)) if callable(executor) else str(executor)

        # 回退到 LangChain @tool 的 .invoke 方法
        for t in self.tools:
            if getattr(t, "name", None) == tool_name:
                try:
                    return str(t.invoke(tool_args))
                except Exception as e:
                    return f"[Tool Error] {tool_name}: {e}"

        return f"[Unknown Tool] {tool_name} not found"

    # =========================================================================
    # 消息提取工具
    # =========================================================================

    def _get_language(self, state: AgentState) -> str:
        """从 State 中提取语言代码，默认 zh"""
        return state.get("language", "zh")

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
            消息列表（混合格式，与 State 中一致）
        """
        messages = state.get("messages", [])
        return list(messages[-(max_turns * 2):])
