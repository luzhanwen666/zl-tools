"""
智能体引擎 - MCP 连接池

按 MCPToolConfig ID 缓存 MCPClient 连接，避免频繁创建/销毁。
每个配置全局复用一个连接，支持按需初始化和集中关闭。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .mcp_client import MCPClient, MCPError

if TYPE_CHECKING:
    from mcp_tools.models import MCPToolConfig

logger = logging.getLogger(__name__)


class MCPConnectionPool:
    """MCP 连接池 — 按 MCPToolConfig.pk 管理连接生命周期"""

    _instance: "MCPConnectionPool | None" = None

    def __init__(self):
        self._clients: dict[int, MCPClient] = {}
        self._tool_caches: dict[int, list[dict]] = {}  # pk → tools list

    @classmethod
    def get_instance(cls) -> "MCPConnectionPool":
        """获取全局单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_client(self, mcp_config: "MCPToolConfig") -> MCPClient:
        """
        获取或创建 MCP 客户端连接。

        Args:
            mcp_config: MCP 工具配置模型实例

        Returns:
            MCPClient: 已连接的客户端

        Raises:
            MCPError: 连接失败
        """
        pk = mcp_config.pk

        if pk in self._clients:
            client = self._clients[pk]
            # 简单健康检查（SSE 连接需要 session，stdio 需要进程存活）
            if client._transport == "stdio" and client._process:
                if client._process.returncode is not None:
                    logger.warning("MCP stdio process died (pk=%d), reconnecting...", pk)
                    await client.close()
                    del self._clients[pk]
                    self._tool_caches.pop(pk, None)
                else:
                    return client

        # 创建新连接
        client = MCPClient()
        try:
            if mcp_config.transport == "stdio":
                await client.connect_stdio(
                    command=mcp_config.server_url,
                    args=mcp_config.args or [],
                    env=mcp_config.env_vars or {},
                )
            else:  # sse
                await client.connect_sse(mcp_config.server_url)

            # 预加载工具列表
            tools = await client.list_tools()
            self._tool_caches[pk] = tools
            logger.info("MCP pool: connected to %s (%d tools)", mcp_config.name, len(tools))

        except Exception as e:
            await client.close()
            raise MCPError(f"连接 MCP 服务 '{mcp_config.name}' 失败: {e}")

        self._clients[pk] = client
        return client

    def get_cached_tools(self, mcp_config: "MCPToolConfig") -> list[dict]:
        """获取缓存的工具列表（不触发连接）"""
        return self._tool_caches.get(mcp_config.pk, [])

    async def close_config(self, mcp_config: "MCPToolConfig") -> None:
        """关闭指定 MCP 配置的连接"""
        pk = mcp_config.pk
        if pk in self._clients:
            await self._clients[pk].close()
            del self._clients[pk]
            self._tool_caches.pop(pk, None)
            logger.info("MCP pool: closed %s", mcp_config.name)

    async def close_all(self) -> None:
        """关闭所有连接"""
        for pk, client in list(self._clients.items()):
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        self._tool_caches.clear()
        logger.info("MCP pool: all connections closed")
