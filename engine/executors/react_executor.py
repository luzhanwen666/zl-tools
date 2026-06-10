"""
智能体引擎 - ReAct 执行器

Thought → Action → Observation 循环。
从原 AgentRunner 提取逻辑，保持核心行为不变。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from .base_executor import BaseAgentExecutor, AgentExecutionResult
from engine.schemas import ToolCall

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from engine.schemas import AgentMessage

logger = logging.getLogger(__name__)

# ── 工具调用提取（从 agent_runner.py 移植）─────────────────────────────


def _extract_tool_calls(response_text: str) -> list[ToolCall]:
    """从 LLM 回复中提取工具调用"""
    tool_calls = []

    code_block_pattern = r"```(?:tool|json)?\s*\n?(\{[^`]*\})\s*\n?```"
    for match in re.finditer(code_block_pattern, response_text, re.DOTALL):
        try:
            data = json.loads(match.group(1))
            if "tool" in data:
                tool_calls.append(ToolCall(
                    id=f"call_{len(tool_calls)}",
                    name=data["tool"],
                    arguments=json.dumps(data.get("args", {}), ensure_ascii=False),
                ))
        except json.JSONDecodeError:
            continue

    if not tool_calls:
        json_objects = _extract_json_objects(response_text)
        for obj_str in json_objects:
            try:
                data = json.loads(obj_str)
                if isinstance(data, dict) and "tool" in data:
                    tool_calls.append(ToolCall(
                        id=f"call_{len(tool_calls)}",
                        name=data["tool"],
                        arguments=json.dumps(data.get("args", {}), ensure_ascii=False),
                    ))
            except (json.JSONDecodeError, TypeError):
                continue

    return tool_calls


def _extract_json_objects(text: str) -> list[str]:
    """从文本中提取所有花括号平衡的 JSON 对象字符串"""
    objects = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        objects.append(text[start:i + 1])
                        break
                i += 1
        else:
            i += 1
    return objects


def _strip_tool_calls(text: str) -> str:
    """从回复文本中移除工具调用部分"""
    text = re.sub(r"```(?:tool|json)?\s*\n?\{[^`]*\"tool\"[^`]*\}\s*\n?```", "", text, flags=re.DOTALL)
    text = re.sub(r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}', "", text)
    return text.strip()


def _is_finish_signal(text: str) -> bool:
    """检测 Agent 是否表示讨论结束"""
    finish_signals = ["[FINISH]", "[DONE]", "[完成]", "[结束讨论]"]
    return any(signal in text for signal in finish_signals)


# ── ReAct 执行器 ─────────────────────────────────────────────────────


class ReactExecutor(BaseAgentExecutor):
    """ReAct 循环执行器 — Thought → Action → Observation"""

    def __init__(self, llm, tool_registry=None, max_turns: int = 5):
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
        messages = self._build_messages(agent, context_messages, tools, system_prompt_override)

        react_messages = list(messages)
        final_content = ""
        all_tool_calls: list[dict] = []
        thinking_trace: list[dict] = []
        status_messages: list[str] = []

        for turn in range(self.max_turns):
            # 限制消息总大小，防止累积过长
            total_size = sum(len(str(m.get("content", ""))) for m in react_messages)
            if total_size > 10000:
                react_messages = [react_messages[0]] + react_messages[-5:]

            status_messages.append(f"思考中 (第 {turn + 1}/{self.max_turns} 轮)...")

            try:
                from engine import llm_client as llm_module
                response = await llm_module.llm_client.chat(
                    provider=self.llm.provider,
                    model_id=self.llm.model_id,
                    messages=react_messages,
                    api_base=self.llm.api_base,
                    api_key=self.llm.api_key,
                    max_tokens=min(self.llm.max_tokens, 4096),
                    temperature=self.llm.temperature,
                )
            except Exception as e:
                logger.error("LLM call failed for agent %s: %s", agent.name, e)
                response = f"[执行错误] LLM 调用失败: {str(e)}"

            tool_calls = _extract_tool_calls(response)
            clean_content = _strip_tool_calls(response)

            # ── 检测 [USE_SKILL:X] 标记（LLM 主动请求技能） ──
            skill_request = None
            try:
                from engine.skills.loader import SkillsLoader
                skill_request = SkillsLoader.detect_skill_request(response, agent)
            except Exception:
                pass

            # 记录本轮思考
            thinking_trace.append({
                "stage": f"react_turn_{turn}",
                "content": response[:1000],
                "tool_calls": [{"tool": tc.name, "args": tc.arguments} for tc in tool_calls],
                "skill_request": skill_request,
            })

            # 无工具调用且无技能请求 → 发言完成
            if not tool_calls and not skill_request:
                final_content = clean_content or response
                status_messages.append("分析完成")
                break

            react_messages.append({"role": "assistant", "content": response})

            # ── 处理 [USE_SKILL:X] ──
            if skill_request:
                status_messages.append(f"加载技能: {skill_request}")
                skill_inst = SkillsLoader.load_layer2_instruction(agent, skill_request)
                react_messages.append({
                    "role": "user",
                    "content": (
                        f"[技能已加载: {skill_request}]\n"
                        f"以下是该技能的完整操作指南，请根据指南继续执行任务：\n\n"
                        f"{skill_inst}\n\n"
                        f"（技能指南已注入上下文，现在你可以调用相关脚本工具了）"
                    ),
                })
                continue  # 下一轮 LLM 会基于技能指南继续执行

            for tc in tool_calls:
                tool_result = "工具未找到"
                if self.tool_registry:
                    try:
                        tool_result = await self.tool_registry.execute_tool(tc.name, tc.arguments)
                    except Exception as e:
                        tool_result = f"工具执行错误: {e}"

                all_tool_calls.append({
                    "tool": tc.name,
                    "args": tc.arguments,
                    "result_preview": tool_result[:200],
                })

                react_messages.append({
                    "role": "user",
                    "content": f"[工具调用结果: {tc.name}]\n{tool_result}",
                })
                status_messages.append(f"调用工具: {tc.name}")
                logger.info("Agent %s called tool %s → %s", agent.name, tc.name, tool_result[:100])

            final_content = clean_content

        if not final_content:
            final_content = "抱歉，我无法在限定步骤内完成此任务。"

        return AgentExecutionResult(
            content=final_content,
            thinking_trace=thinking_trace,
            tool_calls=all_tool_calls,
            stage="done",
            status_messages=status_messages,
        )

    def _build_messages(
        self,
        agent: "AgentModel",
        group_messages: list["AgentMessage"],
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> list[dict]:
        """构建发送给 LLM 的消息列表"""
        messages = []
        system_prompt = system_prompt_override or agent.system_prompt or "你是一个智能助手。"

        if tools:
            tool_desc = "\n\n## 可用工具\n"
            for tool in tools:
                tool_desc += f"- **{tool.name}**: {tool.description}\n"
            system_prompt += tool_desc

        # 限制 system_prompt 长度
        max_prompt = 2500
        if len(system_prompt) > max_prompt:
            system_prompt = system_prompt[:max_prompt] + "\n...(已截断)"

        messages.append({"role": "system", "content": system_prompt})

        for msg in group_messages[-8:]:  # 最近8条
            content = msg.content
            if len(content) > 1500:
                content = content[:1500] + "...(截断)"
            msg_dict = msg.to_openai_message()
            msg_dict["content"] = content
            messages.append(msg_dict)

        return messages
