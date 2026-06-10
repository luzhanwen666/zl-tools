"""
智能体引擎 - 统一 LLM 调用客户端

支持多供应商（OpenAI / Anthropic / DeepSeek / Ollama 等），
统一为 OpenAI 兼容 API 格式进行调用。
"""

import json
import logging
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)


# 供应商默认 API 地址映射
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
    "azure_openai": "",
    "google": "",
    "other": "",
}


def _build_anthropic_url(base_url: str) -> str:
    """
    构建 Anthropic API 的完整 URL。

    处理三种情况：
    1. 未配置 api_base → https://api.anthropic.com/v1/messages
    2. 已配置但不含 /v1 → 补上 /v1/messages（如 https://my-proxy.com  → .../v1/messages）
    3. 已配置且尾部有 /v1 → 直接拼 /messages（如 .../api/anthropic/v1 → .../v1/messages）
       （避免出现 .../v1/v1/messages）
    """
    if not base_url:
        return "https://api.anthropic.com/v1/messages"
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


class LLMClient:
    """统一 LLM 调用客户端"""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def chat(
        self,
        provider: str,
        model_id: str,
        messages: list[dict],
        api_base: str = "",
        api_key: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """
        统一调用接口。

        Args:
            provider: 供应商标识（openai / anthropic / deepseek / ollama 等）
            model_id: 模型 ID
            messages: 消息列表 [{"role": "user", "content": "..."}, ...]
            api_base: API 地址（为空则使用供应商默认值）
            api_key: API Key
            max_tokens: 最大生成 token 数
            temperature: 温度
            tools: 工具定义列表（OpenAI function calling 格式）
            stream: 是否流式输出

        Returns:
            非流式: 返回完整文本
            流式: 返回异步生成器，逐步产出文本片段
        """
        base_url = api_base or DEFAULT_BASE_URLS.get(provider, "")

        if provider == "anthropic":
            if stream:
                return self._stream_anthropic(base_url, model_id, messages, api_key, max_tokens, temperature, tools)
            return await self._chat_anthropic(base_url, model_id, messages, api_key, max_tokens, temperature, tools)

        # OpenAI 兼容格式（openai / deepseek / ollama / azure_openai / other）
        if stream:
            return self._stream_openai(base_url, model_id, messages, api_key, max_tokens, temperature, tools)
        return await self._chat_openai(base_url, model_id, messages, api_key, max_tokens, temperature, tools)

    # ------------------------------------------------------------------
    # OpenAI 兼容格式（openai / deepseek / ollama）
    # ------------------------------------------------------------------

    async def _chat_openai(
        self, base_url: str, model: str, messages: list[dict],
        api_key: str, max_tokens: int, temperature: float,
        tools: list[dict] | None,
    ) -> str:
        """非流式调用 OpenAI 兼容 API"""
        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        # 处理工具调用
        if message.get("tool_calls"):
            return json.dumps(message, ensure_ascii=False)

        return message.get("content", "")

    async def _stream_openai(
        self, base_url: str, model: str, messages: list[dict],
        api_key: str, max_tokens: int, temperature: float,
        tools: list[dict] | None,
    ) -> AsyncGenerator[str, None]:
        """流式调用 OpenAI 兼容 API"""
        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{base_url}/chat/completions", json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    # ------------------------------------------------------------------
    # Anthropic 格式
    # ------------------------------------------------------------------

    async def _chat_anthropic(
        self, base_url: str, model: str, messages: list[dict],
        api_key: str, max_tokens: int, temperature: float,
        tools: list[dict] | None,
    ) -> str:
        """非流式调用 Anthropic API"""
        # 提取 system 消息
        system_content = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                api_messages.append(msg)

        payload: dict = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_content.strip():
            payload["system"] = system_content.strip()
        if tools:
            payload["tools"] = self._convert_tools_to_anthropic(tools)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        url = _build_anthropic_url(base_url)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("Anthropic response: %s", json.dumps(data, ensure_ascii=False)[:300])

        content_parts = []
        tool_use_parts = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_use_parts.append(block)

        if tool_use_parts:
            return json.dumps({"content": "\n".join(content_parts), "tool_uses": tool_use_parts}, ensure_ascii=False)

        result = "\n".join(content_parts).strip()
        if not result:
            # Anthropic 可能把短回复放到别的结构里，尝试从 stop_reason 或额外字段取
            result = str(data.get("stop_reason", ""))
            logger.warning("Anthropic returned empty content, stop_reason=%s", result)
        return result

    async def _stream_anthropic(
        self, base_url: str, model: str, messages: list[dict],
        api_key: str, max_tokens: int, temperature: float,
        tools: list[dict] | None,
    ) -> AsyncGenerator[str, None]:
        """流式调用 Anthropic API"""
        system_content = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                api_messages.append(msg)

        payload: dict = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_content.strip():
            payload["system"] = system_content.strip()
        if tools:
            payload["tools"] = self._convert_tools_to_anthropic(tools)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        url = f"{base_url}/v1/messages" if base_url else "https://api.anthropic.com/v1/messages"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                    except json.JSONDecodeError:
                        continue

    # ------------------------------------------------------------------
    # 工具格式转换
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools_to_anthropic(openai_tools: list[dict]) -> list[dict]:
        """将 OpenAI 工具格式转换为 Anthropic 格式"""
        anthropic_tools = []
        for tool in openai_tools:
            func = tool.get("function", tool)
            at = {
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            }
            anthropic_tools.append(at)
        return anthropic_tools


# 模块级单例
llm_client = LLMClient()
