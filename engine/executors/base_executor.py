"""
智能体引擎 - 执行器抽象基类

定义 AgentExecutionResult 和 BaseAgentExecutor，所有 Agent 执行策略的公共接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from llm_config.models import LLMConfig
    from engine.schemas import AgentMessage
    from engine.tools.base import ToolRegistry


@dataclass
class AgentExecutionResult:
    """Agent 执行结果 — 包含完整的思考追溯和中间状态"""

    content: str = ""                             # 最终回复文本
    thinking_trace: list[dict] = field(default_factory=list)
    # thinking_trace 格式: [{"stage": "react_turn_0|generate|reflect|refine|plan|execute_step_0",
    #                         "content": "...", "tool_calls": [...]}]
    tool_calls: list[dict] = field(default_factory=list)  # 全部工具调用汇总
    stage: str = "done"                           # planning|executing|reflecting|generating|done
    status_messages: list[str] = field(default_factory=list)  # 给前端的实时状态文本

    def to_agent_message(self, agent_name: str = "") -> "AgentMessage":
        """转换为 AgentMessage（用于群聊/编排器）"""
        from engine.schemas import AgentMessage
        return AgentMessage(
            role="assistant",
            content=self.content,
            name=agent_name,
            tool_calls=self.tool_calls,
            metadata={
                "thinking": self.thinking_trace,
                "stage": self.stage,
                "status_messages": self.status_messages,
                "agent_type": getattr(self, "agent_type", "react"),
            },
        )


class BaseAgentExecutor(ABC):
    """Agent 执行器抽象基类 — 所有执行策略（ReAct/Simple/Reflection/PlanAndSolve）的公共接口"""

    def __init__(self, llm: "LLMConfig", tool_registry: "ToolRegistry | None" = None):
        self.llm = llm
        self.tool_registry = tool_registry

    @abstractmethod
    async def execute(
        self,
        agent: "AgentModel",
        user_message: str | None,
        context_messages: list["AgentMessage"],
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentExecutionResult:
        """
        执行 Agent 的完整推理流程。

        Args:
            agent: Agent 模型实例（含 system_prompt、llm_config 等配置）
            user_message: 用户当前输入（可能为 None，如纯上下文驱动的执行）
            context_messages: 已有的上下文消息（对话历史、协调者指令等）
            tools: 此 Agent 可用的工具列表
            system_prompt_override: 覆盖默认 system_prompt（编排器会注入增强提示词）

        Returns:
            AgentExecutionResult: 包含最终回复、思考追溯、工具调用等完整信息
        """
        ...
