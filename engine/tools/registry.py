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
    """将 MCPToolConfig 包装为工具（预留，后续实现实际 MCP 调用）"""

    def __init__(self, mcp_config):
        self.name = f"mcp_{mcp_config.name.lower().replace(' ', '_')}"
        self.description = mcp_config.description or f"MCP工具: {mcp_config.name}"
        self.mcp_config = mcp_config
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作",
                },
                "params": {
                    "type": "object",
                    "description": "操作参数",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, params: dict | None = None, **kwargs) -> str:
        """MCP 工具执行（预留实现）"""
        # TODO: 实际调用 MCP 服务
        logger.info("MCP tool call: %s, action: %s, params: %s", self.mcp_config.name, action, params)
        return f"[MCP: {self.mcp_config.name}] Action: {action}. (MCP 调用尚未实现)"


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
