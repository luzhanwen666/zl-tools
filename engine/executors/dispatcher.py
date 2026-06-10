"""
智能体引擎 - 执行器调度工厂

根据 Agent.agent_type 分发到正确的执行策略。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base_executor import BaseAgentExecutor
from .react_executor import ReactExecutor
from .simple_executor import SimpleExecutor
from .reflection_executor import ReflectionExecutor
from .plan_and_solve_executor import PlanAndSolveExecutor

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from llm_config.models import LLMConfig
    from engine.tools.base import ToolRegistry


def get_executor(
    agent: "AgentModel",
    llm_config: "LLMConfig | None" = None,
    tool_registry: "ToolRegistry | None" = None,
) -> BaseAgentExecutor:
    """
    根据 Agent 的 agent_type 返回对应的执行器实例。

    Args:
        agent: Agent 模型实例（必须含 agent_type 字段）
        llm_config: LLM 配置（可覆盖 agent.llm_config）
        tool_registry: 工具注册中心

    Returns:
        BaseAgentExecutor: 对应类型的执行器

    Agent type → Executor mapping:
        "react"          → ReactExecutor (Thought-Action-Observation 循环)
        "simple"         → SimpleExecutor (直接问答)
        "reflection"     → ReflectionExecutor (生成-反思-改进)
        "plan_and_solve" → PlanAndSolveExecutor (先规划后执行)
    """
    llm = llm_config or agent.llm_config
    if not llm:
        raise ValueError(f"Agent '{agent.name}' 未配置大模型，无法创建执行器")

    agent_type = getattr(agent, "agent_type", "react") or "react"

    if agent_type == "simple":
        return SimpleExecutor(llm, tool_registry)
    elif agent_type == "reflection":
        return ReflectionExecutor(llm, tool_registry)
    elif agent_type == "plan_and_solve":
        return PlanAndSolveExecutor(llm, tool_registry)
    else:
        # 默认 ReAct（包括 "react" 及其他未知值）
        return ReactExecutor(llm, tool_registry)


# ── 向后兼容的便捷函数 ──────────────────────────────────────────────


def run_agent(
    agent: "AgentModel",
    user_message: str | None = None,
    context_messages: list | None = None,
    tools: list | None = None,
    system_prompt_override: str | None = None,
    tool_registry: "ToolRegistry | None" = None,
):
    """
    便捷函数 — 根据 agent_type 自动选择执行器并执行。
    返回 AgentExecutionResult。
    """
    executor = get_executor(agent, tool_registry=tool_registry)
    return executor.execute(
        agent=agent,
        user_message=user_message,
        context_messages=context_messages or [],
        tools=tools,
        system_prompt_override=system_prompt_override,
    )
