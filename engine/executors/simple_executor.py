"""
SimpleAgent 执行器 — 直接问答 + [USE_SKILL:X] 主动触发 + 工具调用循环
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .base_executor import BaseAgentExecutor, AgentExecutionResult
from .react_executor import _extract_tool_calls, _strip_tool_calls

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from engine.schemas import AgentMessage

logger = logging.getLogger(__name__)


class SimpleExecutor(BaseAgentExecutor):
    """简单执行器 — 单次 LLM 调用，但支持 [USE_SKILL:X] 和工具调用循环"""

    def __init__(self, llm, tool_registry=None, max_turns: int = 4):
        super().__init__(llm, tool_registry)
        self.max_turns = max_turns

    async def execute(
        self,
        agent: "AgentModel",
        user_message: str | None = None,
        context_messages: list["AgentMessage"] | None = None,
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentExecutionResult:
        context_messages = context_messages or []

        messages = [{"role": "system", "content": (system_prompt_override or agent.system_prompt or "你是智能助手。")}]
        for msg in context_messages[-4:]:
            c = msg.content[:1000] if len(msg.content) > 1000 else msg.content
            messages.append({"role": "assistant" if msg.role == "assistant" else "user", "content": c})
        if user_message:
            messages.append({"role": "user", "content": user_message})

        # 工具描述注入
        if tools:
            td = "\n\n## 可用工具\n" + "\n".join(f"- **{t.name}**: {getattr(t, 'description', '')}" for t in tools[:15])
            messages[0]["content"] += td

        thinking_trace: list[dict] = []
        status_messages: list[str] = []
        all_tool_calls: list[dict] = []
        skills_used: list[str] = []
        final_content = ""
        react_messages = list(messages)

        for turn in range(self.max_turns):
            status_messages.append(f"思考中 ({turn+1}/{self.max_turns})...")

            try:
                from engine import llm_client as llm_module
                response = await llm_module.llm_client.chat(
                    provider=self.llm.provider, model_id=self.llm.model_id,
                    messages=react_messages, api_base=self.llm.api_base,
                    api_key=self.llm.api_key,
                    max_tokens=min(self.llm.max_tokens, 4096),
                    temperature=self.llm.temperature,
                )
            except Exception as e:
                logger.error("SimpleExecutor LLM failed: %s", e)
                response = f"[执行错误] {e}"

            tool_calls = _extract_tool_calls(response)
            clean_content = _strip_tool_calls(response)

            thinking_trace.append({
                "stage": f"turn_{turn}",
                "content": response[:1000],
                "tool_calls": [{"tool": tc.name, "args": tc.arguments} for tc in tool_calls],
            })

            # ── 1. 处理 [USE_SKILL:X] ──
            skill_handled = await self._handle_skill_requests(
                response, agent, react_messages, status_messages, skills_used
            )

            if skill_handled:
                react_messages.append({"role": "assistant", "content": response})
                continue  # 下一轮 LLM 基于技能指南+工具列表继续

            # ── 2. 处理工具调用 ──
            if tool_calls:
                react_messages.append({"role": "assistant", "content": response})
                for tc in tool_calls:
                    tool_result = "工具未找到"
                    if self.tool_registry:
                        try:
                            tool_result = await self.tool_registry.execute_tool(tc.name, tc.arguments)
                        except Exception as e:
                            tool_result = f"工具错误: {e}"
                    all_tool_calls.append({"tool": tc.name, "args": tc.arguments, "result_preview": tool_result[:300]})
                    react_messages.append({"role": "user", "content": f"[工具结果: {tc.name}]\n{tool_result}"})
                    status_messages.append(f"执行: {tc.name}")
                continue

            # ── 3. 无工具 + 无技能 → 完成 ──
            final_content = clean_content or response
            status_messages.append("完成")
            break

        if not final_content:
            final_content = "抱歉，我无法在限定步骤内完成此任务。"

        return AgentExecutionResult(
            content=final_content, thinking_trace=thinking_trace,
            tool_calls=all_tool_calls, stage="done",
            status_messages=status_messages, skills_used=skills_used,
        )
