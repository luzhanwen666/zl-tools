"""
智能体引擎 - Agent 执行器（ReAct 循环）

向后兼容的薄包装层：内部委托给 engine.executors 中的对应执行器。
根据 Agent.agent_type 自动选择执行策略。
"""

import logging
from typing import TYPE_CHECKING

from .executors import get_executor, AgentExecutionResult
from .schemas import AgentMessage, ToolCall

# 重新导出工具函数（向后兼容）
from .executors.react_executor import (
    _extract_tool_calls,
    _extract_json_objects,
    _strip_tool_calls,
    _is_finish_signal,
)

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    单个 Agent 的执行器（向后兼容包装）。

    内部根据 agent.agent_type 委托给对应的 executor：
    - "react" → ReactExecutor（默认）
    - "simple" → SimpleExecutor
    - "reflection" → ReflectionExecutor
    - "plan_and_solve" → PlanAndSolveExecutor
    """

    def __init__(self, llm: "LLMConfig", tool_registry: "ToolRegistry | None" = None):
        self.llm = llm
        self.tool_registry = tool_registry
        self.max_react_turns = 5

    async def run(
        self,
        agent: "AgentModel",
        group_messages: list[AgentMessage],
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentMessage:
        """
        执行单个 Agent 的完整推理流程。

        内部委托给对应 agent_type 的 executor。
        """
        # 从 group_messages 中提取用户消息（最后一条 user 消息）
        user_msg = ""
        for msg in reversed(group_messages):
            if msg.role == "user":
                user_msg = msg.content
                break

        executor = get_executor(agent, self.llm, self.tool_registry)

        try:
            result: AgentExecutionResult = await executor.execute(
                agent=agent,
                user_message=user_msg,
                context_messages=group_messages,
                tools=tools,
                system_prompt_override=system_prompt_override,
            )
        except Exception as e:
            logger.exception("AgentRunner execution failed for %s", agent.name)
            return AgentMessage(
                role="assistant",
                content=f"[执行错误] {agent.name}: {str(e)}",
                name=agent.name,
            )

        return result.to_agent_message(agent.name)
