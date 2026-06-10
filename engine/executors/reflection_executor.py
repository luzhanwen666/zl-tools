"""
智能体引擎 - ReflectionAgent 执行器

三阶段：Generate（生成初稿）→ Reflect（批判审视）→ Refine（改进答案）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base_executor import BaseAgentExecutor, AgentExecutionResult
from .reflection_prompts import (
    REFLECTION_INITIAL_PROMPT,
    REFLECTION_CRITIQUE_PROMPT,
    REFLECTION_REFINE_PROMPT,
)

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from engine.schemas import AgentMessage

logger = logging.getLogger(__name__)


class ReflectionExecutor(BaseAgentExecutor):
    """反思执行器 — Generate → Reflect → Refine

    支持通过 custom_prompts 参数传入自定义的三阶段提示词。
    """

    def __init__(self, llm, tool_registry=None, custom_prompts: dict | None = None):
        super().__init__(llm, tool_registry)
        self.prompts = {
            "initial": custom_prompts.get("initial") if custom_prompts else REFLECTION_INITIAL_PROMPT,
            "reflect": custom_prompts.get("reflect") if custom_prompts else REFLECTION_CRITIQUE_PROMPT,
            "refine": custom_prompts.get("refine") if custom_prompts else REFLECTION_REFINE_PROMPT,
        }

    async def execute(
        self,
        agent: "AgentModel",
        user_message: str | None = None,
        context_messages: list["AgentMessage"] | None = None,
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentExecutionResult:
        task = user_message or "请完成你的任务"
        thinking_trace: list[dict] = []
        status_messages: list[str] = []

        # ── 阶段 1: Generate 初稿 ──────────────────────────────────
        status_messages.append("阶段 1/3: 生成初稿...")
        initial_prompt = self.prompts["initial"].format(task=task)

        initial_response = await self._call_llm(agent, initial_prompt, context_messages,
                                                tools, system_prompt_override)
        thinking_trace.append({"stage": "generate", "content": initial_response[:800]})

        # 检查是否完成信号
        if "[FINAL]" in initial_response or "[FINISH]" in initial_response:
            return AgentExecutionResult(
                content=initial_response.replace("[FINAL]", "").replace("[FINISH]", "").strip(),
                thinking_trace=thinking_trace,
                tool_calls=[],
                stage="done",
                status_messages=status_messages + ["初稿即终稿"],
            )

        # ── 阶段 2: Reflect 反思 ────────────────────────────────────
        status_messages.append("阶段 2/3: 批判审视...")
        reflect_prompt = self.prompts["reflect"].format(task=task, content=initial_response)

        critique_response = await self._call_llm(agent, reflect_prompt, context_messages,
                                                  tools, system_prompt_override)
        thinking_trace.append({"stage": "reflect", "content": critique_response[:800]})

        # 无需改进 → 直接返回初稿
        if "无需改进" in critique_response:
            status_messages.append("评估通过，无需改进")
            return AgentExecutionResult(
                content=initial_response,
                thinking_trace=thinking_trace,
                tool_calls=[],
                stage="done",
                status_messages=status_messages,
            )

        # ── 阶段 3: Refine 改进 ─────────────────────────────────────
        status_messages.append("阶段 3/3: 改进答案...")
        refine_prompt = self.prompts["refine"].format(
            task=task,
            last_attempt=initial_response,
            feedback=critique_response,
        )

        final_response = await self._call_llm(agent, refine_prompt, context_messages,
                                               tools, system_prompt_override)
        thinking_trace.append({"stage": "refine", "content": final_response[:800]})

        status_messages.append("完成（已改进）")
        return AgentExecutionResult(
            content=final_response,
            thinking_trace=thinking_trace,
            tool_calls=[],
            stage="done",
            status_messages=status_messages,
        )

    async def _call_llm(
        self,
        agent: "AgentModel",
        prompt: str,
        context_messages: list["AgentMessage"] | None = None,
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> str:
        """单次 LLM 调用"""
        context_messages = context_messages or []
        messages = []

        base_system = system_prompt_override or agent.system_prompt or "你是一个专业的AI助手。"

        # 工具描述注入
        if tools:
            tool_desc = "\n\n## 可用工具\n"
            for tool in tools:
                tool_desc += f"- **{tool.name}**: {tool.description}\n"
            base_system += tool_desc

        messages.append({"role": "system", "content": base_system[:3000]})

        for msg in context_messages[-4:]:
            content = msg.content[:1000] if len(msg.content) > 1000 else msg.content
            messages.append({"role": "assistant" if msg.role == "assistant" else "user",
                             "content": content})

        messages.append({"role": "user", "content": prompt})

        try:
            from engine import llm_client as llm_module
            return await llm_module.llm_client.chat(
                provider=self.llm.provider,
                model_id=self.llm.model_id,
                messages=messages,
                api_base=self.llm.api_base,
                api_key=self.llm.api_key,
                max_tokens=min(self.llm.max_tokens, 4096),
                temperature=self.llm.temperature,
            )
        except Exception as e:
            logger.error("ReflectionExecutor LLM call failed: %s", e)
            return f"[执行错误] LLM 调用失败: {str(e)}"
