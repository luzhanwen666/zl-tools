"""
智能体引擎 - MCP 协议客户端

完整的 JSON-RPC 2.0 协议实现，支持 Stdio 和 SSE 两种传输方式。
参考：Model Context Protocol 规范 https://modelcontextprotocol.io/

Stdio 模式：启动子进程，通过 stdin/stdout 进行 JSON-RPC 通信
SSE 模式：GET /sse 获取会话端点，POST 发送 JSON-RPC，SSE 流接收响应
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

MCP_VERSION = "2024-11-05"
REQUEST_TIMEOUT = 30  # 秒


class MCPError(Exception):
    """MCP 协议错误"""
    pass


class MCPClient:
    """
    MCP 协议客户端 — JSON-RPC 2.0 over Stdio / SSE.

    Stdio 用法:
        client = MCPClient()
        await client.connect_stdio("python", ["mcp_server.py"], {"API_KEY": "xxx"})
        tools = await client.list_tools()
        result = await client.call_tool("tool_name", {"param": "value"})
        await client.close()

    SSE 用法:
        client = MCPClient()
        await client.connect_sse("https://mcp.example.com")
        tools = await client.list_tools()
        result = await client.call_tool("tool_name", {"param": "value"})
        await client.close()
    """

    def __init__(self):
        self._transport: str = ""  # "stdio" | "sse"
        self._request_id: int = 0

        # Stdio 状态
        self._process: asyncio.subprocess.Process | None = None
        self._stdio_lock: asyncio.Lock | None = None

        # SSE 状态
        self._session: aiohttp.ClientSession | None = None
        self._sse_url: str = ""
        self._message_url: str = ""

    # ── Stdio 传输 ───────────────────────────────────────────────

    async def connect_stdio(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict:
        """
        启动 MCP 子进程并通过 stdin/stdout 建立 JSON-RPC 连接。

        Args:
            command: 可执行文件路径（如 "python", "node"）
            args: 命令行参数（如 ["mcp_server.py"]）
            env: 额外的环境变量

        Returns:
            dict: initialize 响应的 capabilities
        """
        self._transport = "stdio"
        env_full = None
        if env:
            import os
            env_full = os.environ.copy()
            env_full.update(env)

        cmd = [command] + (args or [])
        logger.info("MCP stdio: starting %s", cmd)

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_full,
        )
        self._stdio_lock = asyncio.Lock()

        # 发送 initialize 请求
        init_result = await self._initialize()
        logger.info("MCP stdio initialized: %s", init_result.get("capabilities", {}))
        return init_result

    # ── SSE 传输 ─────────────────────────────────────────────────

    async def connect_sse(self, server_url: str) -> dict:
        """
        通过 SSE 连接到 MCP 服务器。

        流程：
        1. GET {server_url}/sse → 获取 session endpoint
        2. POST {session_endpoint} 发送 initialize 请求
        3. 建立 SSE 长连接接收响应

        Args:
            server_url: MCP 服务器 URL（如 https://mcp.example.com）

        Returns:
            dict: initialize 响应的 capabilities
        """
        self._transport = "sse"
        self._sse_url = server_url.rstrip("/")

        self._session = aiohttp.ClientSession()

        # Step 1: GET /sse → 获取会话消息端点
        sse_endpoint = f"{self._sse_url}/sse"
        logger.info("MCP SSE: connecting to %s", sse_endpoint)

        try:
            async with self._session.get(sse_endpoint) as resp:
                if resp.status != 200:
                    raise MCPError(f"SSE 连接失败: HTTP {resp.status}")

                # 读取第一条 SSE 事件获取消息端点
                async for line in resp.content:
                    line_text = line.decode("utf-8").strip()
                    if line_text.startswith("data: "):
                        data = json.loads(line_text[6:])
                        self._message_url = data.get("uri", data.get("endpoint", ""))
                        if self._message_url:
                            break
                    elif line_text.startswith("event: endpoint"):
                        # 有些实现用 event 行
                        continue

            if not self._message_url:
                raise MCPError("SSE 连接未返回消息端点")

            # 补全相对 URL
            if self._message_url.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(self._sse_url)
                self._message_url = f"{parsed.scheme}://{parsed.netloc}{self._message_url}"

            logger.info("MCP SSE: message endpoint = %s", self._message_url)

        except aiohttp.ClientError as e:
            raise MCPError(f"SSE 连接失败: {e}")

        # Step 2: 发送 initialize 请求
        return await self._initialize()

    # ── JSON-RPC 核心 ────────────────────────────────────────────

    async def _initialize(self) -> dict:
        """发送 initialize 请求 + initialized 通知"""
        result = await self._send_request("initialize", {
            "protocolVersion": MCP_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "agent-platform",
                "version": "1.0.0",
            },
        })

        # 发送 initialized 通知（无需等待响应）
        await self._send_notification("notifications/initialized", {})

        return result

    async def _send_request(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应"""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        if self._transport == "stdio":
            return await self._stdio_send(request)
        else:
            return await self._sse_send(request)

    async def _send_notification(self, method: str, params: dict) -> None:
        """发送 JSON-RPC 通知（无 id，不等待响应）"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        if self._transport == "stdio":
            await self._stdio_send_raw(notification)
        else:
            await self._sse_send(notification)

    # ── Stdio 通信 ───────────────────────────────────────────────

    async def _stdio_send(self, request: dict) -> dict:
        """通过 stdio 发送请求并等待响应"""
        async with self._stdio_lock:
            await self._stdio_send_raw(request)

            # 读取响应
            if self._process.stdout.at_eof():
                raise MCPError("MCP 子进程已关闭")

            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=REQUEST_TIMEOUT,
                )
            except asyncio.TimeoutError:
                raise MCPError("MCP stdio 响应超时")

            if not line:
                raise MCPError("MCP 子进程无响应")

            try:
                response = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError as e:
                # 有些服务器会输出日志到 stdout，尝试跳过非 JSON 行
                logger.warning("MCP stdio non-JSON output: %s", line[:200])
                # 重试一次
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=REQUEST_TIMEOUT,
                )
                response = json.loads(line.decode("utf-8").strip())

        if "error" in response:
            raise MCPError(f"MCP Error: {response['error']}")

        return response.get("result", {})

    async def _stdio_send_raw(self, message: dict) -> None:
        """写入 JSON 消息到子进程 stdin"""
        if not self._process or not self._process.stdin:
            raise MCPError("MCP stdio 连接未建立")

        data = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()

    # ── SSE 通信 ─────────────────────────────────────────────────

    async def _sse_send(self, request: dict) -> dict:
        """通过 HTTP POST 发送请求并获取响应"""
        if not self._session or not self._message_url:
            raise MCPError("MCP SSE 连接未建立")

        try:
            async with self._session.post(
                self._message_url,
                json=request,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise MCPError(f"SSE POST 失败: HTTP {resp.status} - {text[:200]}")

                result = await resp.json()

                if "error" in result:
                    raise MCPError(f"MCP Error: {result['error']}")

                return result.get("result", {})

        except aiohttp.ClientError as e:
            raise MCPError(f"SSE 请求失败: {e}")

    # ── MCP 协议方法 ─────────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        """
        tools/list — 获取远程工具列表。

        Returns:
            list[dict]: [{"name": "...", "description": "...", "inputSchema": {...}}, ...]
        """
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        """
        tools/call — 调用远程工具。

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            str: 工具执行结果文本
        """
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

        # 提取文本内容
        content = result.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif item.get("type") == "resource":
                        texts.append(f"[Resource: {item.get('resource', {})}]")
                elif isinstance(item, str):
                    texts.append(item)
            return "\n".join(texts)
        elif isinstance(content, str):
            return content
        return json.dumps(result, ensure_ascii=False)

    async def list_resources(self) -> list[dict]:
        """resources/list — 获取资源列表"""
        result = await self._send_request("resources/list", {})
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> str:
        """resources/read — 读取资源内容"""
        result = await self._send_request("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        if contents:
            return json.dumps(contents, ensure_ascii=False)
        return str(result)

    # ── 生命周期 ─────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 MCP 连接"""
        logger.info("MCP: closing %s connection", self._transport)

        if self._transport == "stdio" and self._process:
            try:
                self._process.stdin.close()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                self._process.kill()
                await self._process.wait()
            self._process = None

        if self._transport == "sse" and self._session:
            await self._session.close()
            self._session = None

        self._transport = ""
        self._message_url = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
