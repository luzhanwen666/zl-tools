"""
智能体引擎 - PlanAndSolveAgent 执行器

阶段一（Plan）：LLM 将复杂任务分解为 3-5 个有序步骤
阶段二（Solve）：对每个步骤依次执行，累积结果
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from .base_executor import BaseAgentExecutor, AgentExecutionResult

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from engine.schemas import AgentMessage

logger = logging.getLogger(__name__)

# ── 默认提示词 ──────────────────────────────────────────────────────

DEFAULT_PLANNER_PROMPT = """你是一个顶级的AI规划专家。你的任务是将用户提出的复杂问题分解成一个由多个简单步骤组成的行动计划。

请确保计划中的每个步骤都是一个独立的、可执行的子任务，并且严格按照逻辑顺序排列。

你的输出必须是一个Python列表，其中每个元素都是一个描述子任务的字符串。

问题: {question}

请严格按照以下格式输出你的计划:
```python
["步骤1", "步骤2", "步骤3", ...]
```"""

DEFAULT_EXECUTOR_PROMPT = """你是一位顶级的AI执行专家。你的任务是严格按照给定的计划，一步步地解决问题。

你将收到原始问题、完整的计划、以及到目前为止已经完成的步骤和结果。
请你专注于解决"当前步骤"，并仅输出该步骤的最终答案。

# 原始问题:
{question}

# 完整计划:
{plan}

# 历史步骤与结果:
{history}

# 当前步骤:
{current_step}

请仅输出针对"当前步骤"的回答:"""


def _extract_plan(response: str) -> list[str]:
    """从 LLM 响应中提取计划步骤列表"""
    # 尝试 Python 列表格式
    python_match = re.search(r'```python\s*\n?(\[.*?\])\s*\n?```', response, re.DOTALL)
    if python_match:
        try:
            plan = json.loads(python_match.group(1))
            if isinstance(plan, list) and len(plan) > 0:
                return plan
        except (json.JSONDecodeError, TypeError):
            pass

    # 尝试纯 JSON 格式
    json_match = re.search(r'\[.*?\]', response, re.DOTALL)
    if json_match:
        try:
            plan = json.loads(json_match.group(0))
            if isinstance(plan, list) and len(plan) > 0:
                return plan
        except (json.JSONDecodeError, TypeError):
            pass

    # 回退：按行分割，取编号行
    lines = response.strip().split("\n")
    steps = []
    for line in lines:
        line = line.strip()
        if re.match(r'^(\d+[\.\)、]\s*)', line):
            step = re.sub(r'^\d+[\.\)、]\s*', '', line)
            steps.append(step.strip('"\'').strip())

    return steps if steps else [response.strip()[:500]]


class PlanAndSolveExecutor(BaseAgentExecutor):
    """规划执行器 — Plan（分解任务）→ Solve（逐步执行）"""

    def __init__(self, llm, tool_registry=None, custom_prompts: dict | None = None):
        super().__init__(llm, tool_registry)
        self.planner_prompt = (custom_prompts or {}).get("planner", DEFAULT_PLANNER_PROMPT)
        self.executor_prompt = (custom_prompts or {}).get("executor", DEFAULT_EXECUTOR_PROMPT)
        self.max_plan_steps = 5

    async def execute(
        self,
        agent: "AgentModel",
        user_message: str | None = None,
        context_messages: list["AgentMessage"] | None = None,
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentExecutionResult:
        task = user_message or "请完成你的任务"
        context_messages = context_messages or []
        thinking_trace: list[dict] = []
        status_messages: list[str] = []
        all_tool_calls: list[dict] = []

        # ── 阶段 1: Plan 规划 ──────────────────────────────────────
        status_messages.append("阶段 1/2: 制定计划...")
        plan_prompt = self.planner_prompt.format(question=task)

        plan_response = await self._call_llm(agent, plan_prompt, context_messages,
                                              tools, system_prompt_override)
        plan_steps = _extract_plan(plan_response)
        plan_steps = plan_steps[:self.max_plan_steps]  # 限制步骤数

        thinking_trace.append({
            "stage": "plan",
            "content": plan_response[:1000],
            "steps": plan_steps,
        })
        status_messages.append(f"计划: {len(plan_steps)} 个步骤")
        logger.info("PlanAndSolve plan: %s", plan_steps)

        # ── 阶段 2: Solve 逐步执行 ──────────────────────────────────
        step_results: list[str] = []
        for i, step in enumerate(plan_steps):
            status_messages.append(f"执行步骤 {i + 1}/{len(plan_steps)}: {step[:60]}...")

            # 构建历史
            history_parts = []
            for j, (s, r) in enumerate(zip(plan_steps[:i], step_results)):
                history_parts.append(f"步骤 {j + 1}: {s}\n结果: {r}")
            history_str = "\n\n".join(history_parts) if history_parts else "（无历史步骤）"

            execute_prompt = self.executor_prompt.format(
                question=task,
                plan="\n".join(f"{j+1}. {s}" for j, s in enumerate(plan_steps)),
                history=history_str,
                current_step=f"步骤 {i + 1}: {step}",
            )

            step_response = await self._call_llm(
                agent, execute_prompt, context_messages, tools, system_prompt_override
            )
            step_results.append(step_response)

            # 如果执行过程中有工具调用，尝试提取
            from .react_executor import _extract_tool_calls, _strip_tool_calls
            tcs = _extract_tool_calls(step_response)
            if tcs and self.tool_registry:
                for tc in tcs:
                    try:
                        tool_result = await self.tool_registry.execute_tool(tc.name, tc.arguments)
                        step_response = f"[工具: {tc.name}] {tool_result[:500]}"
                    except Exception as e:
                        logger.warning("Tool execution failed in PlanAndSolve: %s", e)
                all_tool_calls.extend([{"tool": tc.name, "args": tc.arguments} for tc in tcs])

            thinking_trace.append({
                "stage": f"execute_step_{i}",
                "content": step_response[:800],
                "step": step,
            })

        # ── 合并结果 ────────────────────────────────────────────────
        final_parts = []
        for j, (step, result) in enumerate(zip(plan_steps, step_results)):
            final_parts.append(f"**步骤 {j + 1}: {step}**\n{result}")
        final_content = "\n\n".join(final_parts)

        status_messages.append(f"完成（{len(plan_steps)} 个步骤全部执行）")
        return AgentExecutionResult(
            content=final_content,
            thinking_trace=thinking_trace,
            tool_calls=all_tool_calls,
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
        context_messages = context_messages or []
        messages = []

        base_system = system_prompt_override or agent.system_prompt or "你是一个专业的AI助手。"
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
            logger.error("PlanAndSolveExecutor LLM call failed: %s", e)
            return f"[执行错误] LLM 调用失败: {str(e)}"
