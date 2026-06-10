"""
智能体引擎 - SimpleAgent 执行器

直接问答，无工具循环。适合基础对话、常识问答场景。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base_executor import BaseAgentExecutor, AgentExecutionResult

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from engine.schemas import AgentMessage

logger = logging.getLogger(__name__)


class SimpleExecutor(BaseAgentExecutor):
    """简单执行器 — 单次 LLM 调用，无工具循环"""

    async def execute(
        self,
        agent: "AgentModel",
        user_message: str | None = None,
        context_messages: list["AgentMessage"] | None = None,
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentExecutionResult:
        context_messages = context_messages or []

        system_prompt = system_prompt_override or agent.system_prompt or "你是一个智能助手，请直接回答用户的问题。"

        # 工具描述（如果有绑定工具）仍然注入 system prompt
        if tools:
            tool_desc = "\n\n## 可用工具\n"
            for tool in tools:
                tool_desc += f"- **{tool.name}**: {tool.description}\n"
            system_prompt += tool_desc

        messages = [{"role": "system", "content": system_prompt}]

        # 添加上下文消息
        for msg in context_messages[-6:]:
            content = msg.content
            if len(content) > 1500:
                content = content[:1500] + "...(截断)"
            messages.append({"role": "assistant" if msg.role == "assistant" else "user",
                             "content": content})

        # 添加当前用户消息
        if user_message:
            messages.append({"role": "user", "content": user_message})

        thinking_trace = [{"stage": "generate", "content": "正在生成回答..."}]

        try:
            from engine import llm_client as llm_module
            response = await llm_module.llm_client.chat(
                provider=self.llm.provider,
                model_id=self.llm.model_id,
                messages=messages,
                api_base=self.llm.api_base,
                api_key=self.llm.api_key,
                max_tokens=min(self.llm.max_tokens, 4096),
                temperature=self.llm.temperature,
            )
        except Exception as e:
            logger.error("SimpleExecutor LLM call failed: %s", e)
            response = f"[执行错误] LLM 调用失败: {str(e)}"

        thinking_trace.append({"stage": "done", "content": response[:500]})

        return AgentExecutionResult(
            content=response,
            thinking_trace=thinking_trace,
            tool_calls=[],
            stage="done",
            status_messages=["生成回答", "完成"],
        )
