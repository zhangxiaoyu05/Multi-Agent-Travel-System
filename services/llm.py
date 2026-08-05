"""LLM 工厂——阿里百炼平台（httpx 直连，零 langchain-openai 依赖）

使用 httpx 直接调用百炼 OpenAI 兼容 API，替代 langchain_openai.ChatOpenAI。
减少依赖链、提升异步并发能力、降低包体积。

使用方式：
    from services.llm import get_router_llm, get_agent_llm, get_light_llm
    router_llm = get_router_llm()
    response = router_llm.invoke([{"role": "user", "content": "你好"}])

模型分层策略（成本控制）：
    get_light_llm()  → qwen-turbo   — 客服、运营（检索+工具调用，轻量足矣）
    get_router_llm() → qwen-plus    — 销售、路由、意图识别（中等推理）
    get_agent_llm()  → qwen3-max    — 行程定制（复杂长文本生成，需要最强模型）
"""

import os
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CHAT_PATH = "/chat/completions"
DEFAULT_TIMEOUT = 180.0  # qwen3-max 行程生成可能较慢


# =============================================================================
# LLMResponse —— 替代 langchain AIMessage
# =============================================================================


class LLMResponse:
    """LLM 返回的响应对象，兼容原 langchain AIMessage 的访问模式。

    属性：
        content: str     — 文本回复（可能为空字符串）
        tool_calls: list — [{"id": "...", "name": "...", "args": {...}}, ...]
    """

    __slots__ = ("content", "tool_calls")

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content or ""
        self.tool_calls = tool_calls or []

    def to_message_dict(self) -> dict:
        """转为 OpenAI API 格式的 assistant message dict。

        用于在多轮对话中将 LLM 回复回传给 API。
        """
        msg: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg

    def __repr__(self) -> str:
        return f"<LLMResponse content={self.content[:80]!r} tool_calls={len(self.tool_calls)}>"


# =============================================================================
# BailianLLM
# =============================================================================


class BailianLLM:
    """百炼 LLM 客户端——httpx 直连，兼容 OpenAI 接口。

    提供与原 ChatOpenAI 相同的核心接口：
        invoke(messages)          → LLMResponse
        ainvoke(messages)         → LLMResponse (async)
        bind_tools(tools)         → _ToolBoundLLM（携带 tools 的可调用对象）
        with_structured_output()  → _StructuredOutputLLM（解析为 Pydantic 的可调用对象）

    自动处理混合消息格式（dict / LangChain Message / LLMResponse）。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = BAILIAN_BASE_URL,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        # 同步客户端（惰性创建）
        self._sync_client: httpx.Client | None = None
        # 异步客户端（惰性创建）
        self._async_client: httpx.AsyncClient | None = None

    # =========================================================================
    # 公共 API
    # =========================================================================

    def invoke(self, messages: list, tools: list | None = None,
               tool_choice: dict | None = None) -> LLMResponse:
        """同步调用 LLM"""
        body = self._build_body(messages, tools, tool_choice)
        headers = self._headers()
        client = self._get_sync_client()
        resp = client.post(self._url, json=body, headers=headers)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    async def ainvoke(self, messages: list, tools: list | None = None,
                      tool_choice: dict | None = None) -> LLMResponse:
        """异步调用 LLM"""
        body = self._build_body(messages, tools, tool_choice)
        headers = self._headers()
        client = self._get_async_client()
        resp = await client.post(self._url, json=body, headers=headers)
        try:
            resp.raise_for_status()
        except Exception as e:
            # 记录详细的错误响应体，方便排查
            import logging
            _log = logging.getLogger(__name__)
            try:
                _log.error(f"LLM API error body: {resp.text[:2000]}")
            except Exception:
                pass
            raise
        return self._parse_response(resp.json())

    async def astream(self, messages: list, tools: list | None = None,
                      tool_choice: dict | None = None):
        """异步流式调用 LLM，逐 token yield 文本块。

        用于前端打字机效果——每 yield 一个 chunk，前端追加渲染。

        Usage:
            async for chunk in llm.astream(messages):
                print(chunk, end="", flush=True)
        """
        body = self._build_body(messages, tools, tool_choice)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        headers = self._headers()

        # 流式请求需要独立 client（避免长连接复用冲突）
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            async with client.stream("POST", self._url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

    def bind_tools(self, tools: list) -> "_ToolBoundLLM":
        """返回绑定了工具的调用对象。

        Usage:
            llm_with_tools = llm.bind_tools([tool1, tool2])
            response = llm_with_tools.invoke(messages)
        """
        openai_tools = [_langchain_tool_to_openai(t) for t in tools]
        return _ToolBoundLLM(self, openai_tools)

    def with_structured_output(self, schema: type[BaseModel]) -> "_StructuredOutputLLM":
        """返回将输出解析为 Pydantic 模型的调用对象。

        内部通过 tool_choice="function" 强制模型调用一个与 schema 对应的函数，
        从函数参数中解析出结构化数据。

        Usage:
            structured = llm.with_structured_output(MyModel)
            result: MyModel = structured.invoke(messages)
        """
        tool_def = _pydantic_to_tool_definition(schema)
        return _StructuredOutputLLM(self, schema, tool_def)

    # =========================================================================
    # 内部方法
    # =========================================================================

    @property
    def _url(self) -> str:
        return f"{self._base_url}{CHAT_PATH}"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        return self._sync_client

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._async_client

    def _build_body(self, messages: list, tools: list | None,
                    tool_choice: dict | None) -> dict:
        body: dict = {
            "model": self.model,
            "messages": _normalize_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        return body

    def _parse_response(self, data: dict) -> LLMResponse:
        """将百炼 API 响应解析为 LLMResponse"""
        choice = data["choices"][0]
        message = choice.get("message", {})
        content = message.get("content") or ""

        tool_calls = []
        raw_calls = message.get("tool_calls") or []
        for tc in raw_calls:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "args": args,
            })

        return LLMResponse(content=content, tool_calls=tool_calls)

    def close(self):
        """关闭 HTTP 客户端"""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None
        # Async client cleanup — caller should await aclose()

    async def aclose(self):
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None


# =============================================================================
# Tool-bound wrapper
# =============================================================================


class _ToolBoundLLM:
    """绑定了 tools 的 LLM 包装器。"""

    def __init__(self, llm: BailianLLM, openai_tools: list):
        self._llm = llm
        self._tools = openai_tools

    def invoke(self, messages: list) -> LLMResponse:
        return self._llm.invoke(messages, tools=self._tools)

    async def ainvoke(self, messages: list) -> LLMResponse:
        return await self._llm.ainvoke(messages, tools=self._tools)

    def astream(self, messages: list):
        """流式调用，透传 tools"""
        return self._llm.astream(messages, tools=self._tools)


# =============================================================================
# Structured-output wrapper
# =============================================================================


class _StructuredOutputLLM:
    """将 LLM 输出强制解析为指定 Pydantic 模型的包装器。

    通过 tool_choice="function" 迫使模型输出结构化 JSON，
    再从 tool_call arguments 中构建 Pydantic 实例。
    """

    def __init__(self, llm: BailianLLM, schema: type[BaseModel], tool_def: dict):
        self._llm = llm
        self._schema = schema
        self._tool_def = tool_def
        self._tool_choice = {
            "type": "function",
            "function": {"name": tool_def["function"]["name"]},
        }

    def invoke(self, messages: list) -> BaseModel:
        response = self._llm.invoke(
            messages, tools=[self._tool_def], tool_choice=self._tool_choice,
        )
        return self._extract(response)

    async def ainvoke(self, messages: list) -> BaseModel:
        response = await self._llm.ainvoke(
            messages, tools=[self._tool_def], tool_choice=self._tool_choice,
        )
        return self._extract(response)

    def _extract(self, response: LLMResponse) -> BaseModel:
        if response.tool_calls:
            return self._schema(**response.tool_calls[0]["args"])
        # Fallback: 尝试从 content 中解析 JSON
        try:
            data = json.loads(response.content)
            return self._schema(**data)
        except (json.JSONDecodeError, Exception):
            raise ValueError(
                f"Failed to parse structured output from: {response.content[:200]!r}"
            )


# =============================================================================
# 工具函数
# =============================================================================


def _normalize_messages(messages: list) -> list[dict]:
    """将混合消息格式统一转为 OpenAI API 的 dict 格式。

    支持：
        - 纯 dict（直接返回）
        - LangChain Message 对象（HumanMessage, AIMessage 等）
        - LLMResponse 对象
    """
    normalized = []
    for m in messages:
        if isinstance(m, dict):
            normalized.append(_normalize_dict_message(m))
        elif isinstance(m, LLMResponse):
            normalized.append(m.to_message_dict())
        elif hasattr(m, "content"):
            # LangChain Message 对象
            role = _langchain_role(m)
            msg = {"role": role, "content": m.content or ""}
            if hasattr(m, "tool_calls") and m.tool_calls:
                msg["tool_calls"] = _normalize_langchain_tool_calls(m.tool_calls)
            normalized.append(msg)
        else:
            logger.warning(f"Unknown message type: {type(m)}, converting to str")
            normalized.append({"role": "user", "content": str(m)})
    return normalized


def _normalize_dict_message(msg: dict) -> dict:
    """确保 dict 消息包含必要的键"""
    if "role" not in msg:
        msg = dict(msg)
        msg.setdefault("role", "user")
    if "content" not in msg:
        msg = dict(msg)
        msg.setdefault("content", "")
    return msg


def _langchain_role(msg) -> str:
    """从 LangChain 消息类型推断 OpenAI role"""
    msg_type = getattr(msg, "type", None)
    if msg_type:
        return msg_type
    class_name = type(msg).__name__.lower()
    role_map = {
        "humanmessage": "user",
        "aimessage": "assistant",
        "systemmessage": "system",
        "toolmessage": "tool",
        "functionmessage": "function",
    }
    return role_map.get(class_name, "user")


def _normalize_langchain_tool_calls(tool_calls: list) -> list[dict]:
    """转换 LangChain tool_calls 格式到 OpenAI 格式"""
    result = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = tc.get("name", "")
            args = tc.get("args", {})
            tc_id = tc.get("id", "")
            result.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
                },
            })
        elif hasattr(tc, "name"):
            result.append({
                "id": getattr(tc, "id", ""),
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(getattr(tc, "args", {}), ensure_ascii=False),
                },
            })
    return result


def _langchain_tool_to_openai(tool) -> dict:
    """将 LangChain @tool 装饰的函数转为 OpenAI function 定义。

    从 tool.args_schema (Pydantic model) 提取 JSON Schema。
    """
    if hasattr(tool, "args_schema") and tool.args_schema is not None:
        schema = tool.args_schema.model_json_schema()
    else:
        schema = {"type": "object", "properties": {}, "required": []}

    # 清理 Pydantic 专用字段
    for field in ("title", "description"):
        schema.pop(field, None)
    # 移除 $defs 避免循环引用
    if "$defs" in schema:
        del schema["$defs"]

    return {
        "type": "function",
        "function": {
            "name": tool.name if hasattr(tool, "name") else getattr(tool, "__name__", "unknown"),
            "description": getattr(tool, "description", "") or "",
            "parameters": schema,
        },
    }


def _pydantic_to_tool_definition(schema: type[BaseModel]) -> dict:
    """将 Pydantic model 转为 OpenAI function 定义（用于 structured output）。"""
    json_schema = schema.model_json_schema()
    for field in ("title", "description"):
        json_schema.pop(field, None)
    if "$defs" in json_schema:
        del json_schema["$defs"]

    return {
        "type": "function",
        "function": {
            "name": schema.__name__,
            "description": f"输出格式: {schema.__name__}",
            "parameters": json_schema,
        },
    }


# =============================================================================
# 模块级单例
# =============================================================================

_router_llm: BailianLLM | None = None
_agent_llm: BailianLLM | None = None
_light_llm: BailianLLM | None = None


def _get_api_key() -> str:
    return os.getenv("LLM_API_KEY", "sk-placeholder")


def get_router_llm() -> BailianLLM:
    """意图路由器用轻量模型（qwen-turbo：快速、低成本）

    环境变量：
        ROUTER_MODEL, LLM_API_KEY, LLM_BASE_URL
        ROUTER_TEMPERATURE（默认 0.3）, ROUTER_MAX_TOKENS（默认 512）
    """
    global _router_llm
    if _router_llm is None:
        _router_llm = BailianLLM(
            model=os.getenv("ROUTER_MODEL", "qwen-plus"),
            api_key=_get_api_key(),
            base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
            temperature=float(os.getenv("ROUTER_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("ROUTER_MAX_TOKENS", "512")),
        )
    return _router_llm


def get_agent_llm() -> BailianLLM:
    """Agent 内容生成用强模型（qwen3-max：长文本、强推理）

    环境变量：
        AGENT_MODEL, LLM_API_KEY, LLM_BASE_URL
        AGENT_TEMPERATURE（默认 0.7）, AGENT_MAX_TOKENS（默认 4096）
    """
    global _agent_llm
    if _agent_llm is None:
        _agent_llm = BailianLLM(
            model=os.getenv("AGENT_MODEL", "qwen3-max"),
            api_key=_get_api_key(),
            base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("AGENT_MAX_TOKENS", "4096")),
        )
    return _agent_llm


def get_light_llm() -> BailianLLM:
    """轻量任务用快速模型（qwen-turbo：极低延迟、最低成本）

    适用于 FAQ 检索回答、CRM/CAPI 工具调用、查询改写等简单任务。
    同样支持 function calling，无需担心工具调用兼容性。

    环境变量：
        LIGHT_MODEL, LLM_API_KEY, LLM_BASE_URL
        LIGHT_TEMPERATURE（默认 0.7）, LIGHT_MAX_TOKENS（默认 2048）
    """
    global _light_llm
    if _light_llm is None:
        _light_llm = BailianLLM(
            model=os.getenv("LIGHT_MODEL", "qwen-plus"),
            api_key=_get_api_key(),
            base_url=os.getenv("LLM_BASE_URL", BAILIAN_BASE_URL),
            temperature=float(os.getenv("LIGHT_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LIGHT_MAX_TOKENS", "2048")),
        )
    return _light_llm
