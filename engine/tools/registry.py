"""
智能体引擎 - 工具注册与管理

负责从 Agent 配置中收集工具：
- 内置工具（builtin/）
- 技能工具（Skill → SkillTool）
- MCP 工具（MCPToolConfig → MCPToolWrapper）
"""

import logging
from typing import TYPE_CHECKING

from .base import BaseTool, ToolRegistry

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel

logger = logging.getLogger(__name__)


class SkillTool(BaseTool):
    """将 Agent Skill 包装为工具"""

    def __init__(self, skill_name: str, skill_description: str, skill_instruction: str):
        self.name = f"skill_{skill_name.lower().replace(' ', '_')}"
        self.description = skill_description
        self.instruction = skill_instruction
        self.parameters = {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "需要使用此技能完成的任务描述",
                }
            },
            "required": ["task"],
        }

    async def execute(self, task: str, **kwargs) -> str:
        """技能执行 — 将 instruction + task 作为上下文返回，由 LLM 根据 instruction 处理"""
        return f"[技能: {self.name}] 任务: {task}\n指令: {self.instruction}\n请根据上述指令完成此任务。"


class MCPToolWrapper(BaseTool):
    """将 MCPToolConfig 包装为工具 — 真实 MCP 协议调用"""

    def __init__(self, mcp_config):
        self.name = f"mcp_{mcp_config.name.lower().replace(' ', '_')}"
        self.description = mcp_config.description or f"MCP工具: {mcp_config.name}"
        self.mcp_config = mcp_config
        self._remote_tools: list[dict] = []  # 从 MCP 服务器获取的工具定义
        self._connected = False
        # 参数 schema 将在首次连接时从远程工具动态构建
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "要执行的操作"},
                "params": {"type": "object", "description": "操作参数"},
            },
            "required": ["action"],
        }

    async def _ensure_connected(self) -> list[dict]:
        """确保已连接到 MCP 服务器并获取工具列表"""
        if not self._connected:
            try:
                from .mcp_pool import MCPConnectionPool
                pool = MCPConnectionPool.get_instance()
                client = await pool.get_client(self.mcp_config)
                self._remote_tools = pool.get_cached_tools(self.mcp_config)
                self._connected = True
                logger.info("MCP tool wrapper connected: %s → %d remote tools",
                           self.mcp_config.name, len(self._remote_tools))
            except Exception as e:
                logger.error("Failed to connect MCP tool '%s': %s", self.mcp_config.name, e)
                self._remote_tools = []
                self._connected = True  # 避免无限重试

        return self._remote_tools

    async def execute(self, action: str = "", params: dict | None = None, **kwargs) -> str:
        """执行 MCP 工具调用"""
        remote_tools = await self._ensure_connected()

        if not remote_tools:
            return f"[MCP: {self.mcp_config.name}] 未连接到远程 MCP 服务，无法执行工具调用。"

        try:
            from .mcp_pool import MCPConnectionPool
            pool = MCPConnectionPool.get_instance()
            client = await pool.get_client(self.mcp_config)

            # 如果 action 匹配某个远程工具名，调用它
            if action:
                matching = [t for t in remote_tools if t.get("name") == action]
                if matching:
                    tool_name = action
                else:
                    tool_name = remote_tools[0].get("name", action)
                    params = {"query": action, **(params or {})}
            else:
                tool_name = remote_tools[0].get("name", "unknown")
                params = params or {}

            result = await client.call_tool(tool_name, params)
            return result

        except Exception as e:
            logger.exception("MCP tool execution failed")
            return f"[MCP错误: {self.mcp_config.name}] {str(e)}"

    def get_remote_tool_definitions(self) -> list[dict]:
        """返回远程工具定义（用于注入 system prompt）"""
        return self._remote_tools


def get_tools_for_agent(agent: "AgentModel", builtin_registry: ToolRegistry | None = None) -> list[BaseTool]:
    """
    收集 Agent 的可用工具（仅限可执行工具，不含技能）。

    技能是行为指南，通过 system_prompt 注入，不属于工具列表。
    工具只包含：MCP 工具、以及将来可配置的内置工具。
    """
    tools: list[BaseTool] = []

    # MCP 工具 → MCPToolWrapper（可执行工具）
    for mcp in agent.mcp_tools.filter(is_active=True):
        tools.append(MCPToolWrapper(mcp))

    # 内置工具 — 所有 Agent 均可使用的通用工具（shell, log_parser, web_search 等）
    if builtin_registry:
        tools.extend(builtin_registry.get_all())

    return tools


# sync_to_async 包装版本，供 async 上下文中安全调用
from asgiref.sync import sync_to_async
get_tools_for_agent_async = sync_to_async(get_tools_for_agent)
