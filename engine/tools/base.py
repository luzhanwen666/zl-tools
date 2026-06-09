"""
智能体引擎 - 工具系统

BaseTool: 工具基类，所有工具（内置工具、MCP工具、技能工具）都继承此类
ToolRegistry: 工具注册中心，管理所有可用工具
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """工具基类"""

    # 子类必须定义的类属性
    name: str = ""
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """
        执行工具。

        Args:
            **kwargs: 工具参数

        Returns:
            工具执行结果的文本描述
        """
        ...

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """注册一个工具"""
        if not tool.name:
            raise ValueError("Tool must have a name")
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def unregister(self, name: str):
        """注销一个工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        """获取所有已注册工具"""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict]:
        """获取所有工具的 OpenAI 格式定义"""
        return [tool.to_openai_tool() for tool in self.get_all()]

    async def execute_tool(self, name: str, arguments: str | dict) -> str:
        """
        执行指定工具。

        Args:
            name: 工具名称
            arguments: 参数（JSON 字符串或字典）

        Returns:
            执行结果文本
        """
        tool = self.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return f"Error: Invalid JSON arguments for tool '{name}'"

        try:
            result = await tool.execute(**arguments)
            return result
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return f"Error executing tool '{name}': {str(e)}"


# 模块级单例
tool_registry = ToolRegistry()
