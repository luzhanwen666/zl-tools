"""
智能体引擎 - Agent 执行器（ReAct 循环）

单个 Agent 的执行引擎：
1. 构建系统提示词（system_prompt + 群聊上下文 + 工具描述）
2. 调用 LLM 获取回复
3. 如果回复中包含工具调用 → 执行工具 → 将结果反馈给 LLM → 继续
4. 如果 Agent 认为当前轮发言完成 → 返回发言内容
"""

import json
import logging
import re
from typing import TYPE_CHECKING

from . import llm_client as llm_module
from .schemas import AgentMessage, ToolCall
from .tools.base import ToolRegistry

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from llm_config.models import LLMConfig

logger = logging.getLogger(__name__)


def _extract_tool_calls(response_text: str) -> list[ToolCall]:
    """
    从 LLM 回复中提取工具调用。

    支持格式:
    1. JSON 格式: {"tool": "name", "args": {...}}
    2. 代码块格式:
       ```tool
       {"tool": "name", "args": {...}}
       ```
    """
    tool_calls = []

    # 尝试提取代码块中的工具调用
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

    # 尝试提取行内 JSON 格式的工具调用（处理嵌套花括号）
    if not tool_calls:
        # 使用花括号平衡的方式提取 JSON 对象
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
    """从回复文本中移除工具调用部分，只保留自然语言内容"""
    # 移除代码块格式的工具调用
    text = re.sub(r"```(?:tool|json)?\s*\n?\{[^`]*\"tool\"[^`]*\}\s*\n?```", "", text, flags=re.DOTALL)
    # 移除行内 JSON 格式的工具调用
    text = re.sub(r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}', "", text)
    return text.strip()


def _is_finish_signal(text: str) -> bool:
    """检测 Agent 是否表示讨论结束"""
    finish_signals = ["[FINISH]", "[DONE]", "[完成]", "[结束讨论]"]
    return any(signal in text for signal in finish_signals)


class AgentRunner:
    """单个 Agent 的 ReAct 执行器"""

    def __init__(self, llm: "LLMConfig", tool_registry: ToolRegistry | None = None):
        self.llm = llm
        self.tool_registry = tool_registry
        self.max_react_turns = 5  # 单次发言最多进行 5 轮 ReAct

    async def run(
        self,
        agent: "AgentModel",
        group_messages: list[AgentMessage],
        tools: list | None = None,
    ) -> AgentMessage:
        """
        执行一次 Agent 发言（可能包含多轮 ReAct 内部循环）。

        Args:
            agent: Agent 模型实例
            group_messages: 群聊历史消息（其他 Agent 的发言）
            tools: 该 Agent 可用的工具列表

        Returns:
            Agent 的发言结果
        """
        # 1. 构建 LLM 消息列表
        messages = self._build_messages(agent, group_messages, tools)

        # 2. ReAct 循环
        react_messages = list(messages)
        final_content = ""

        for turn in range(self.max_react_turns):
            # 调用 LLM
            try:
                response = await llm_module.llm_client.chat(
                    provider=self.llm.provider,
                    model_id=self.llm.model_id,
                    messages=react_messages,
                    api_base=self.llm.api_base,
                    api_key=self.llm.api_key,
                    max_tokens=self.llm.max_tokens,
                    temperature=self.llm.temperature,
                )
            except Exception as e:
                logger.error("LLM call failed for agent %s: %s", agent.name, e)
                response = f"[执行错误] LLM 调用失败: {str(e)}"

            # 检查是否包含工具调用
            tool_calls = _extract_tool_calls(response)
            clean_content = _strip_tool_calls(response)

            if not tool_calls:
                # 没有工具调用，直接返回
                final_content = clean_content or response
                break

            # 有工具调用，执行工具
            react_messages.append({"role": "assistant", "content": response})

            for tc in tool_calls:
                tool_result = "工具未找到"
                if self.tool_registry:
                    tool_result = await self.tool_registry.execute_tool(tc.name, tc.arguments)

                # 将工具结果反馈给 LLM
                react_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
                logger.info("Agent %s called tool %s: %s", agent.name, tc.name, tool_result[:100])

            # LLM 处理工具结果后继续（下一轮循环）
            final_content = clean_content

        return AgentMessage(
            role="assistant",
            content=final_content,
            name=agent.name,
        )

    def _build_messages(
        self,
        agent: "AgentModel",
        group_messages: list[AgentMessage],
        tools: list | None = None,
    ) -> list[dict]:
        """构建发送给 LLM 的消息列表"""
        messages = []

        # 系统提示词
        system_prompt = agent.system_prompt or "你是一个智能助手。"

        # 追加工具描述
        if tools:
            tool_desc = "\n\n## 可用工具\n"
            for tool in tools:
                tool_desc += f"- **{tool.name}**: {tool.description}\n"
            system_prompt += tool_desc

        messages.append({"role": "system", "content": system_prompt})

        # 群聊历史（最近 20 条）
        for msg in group_messages[-20:]:
            messages.append(msg.to_openai_message())

        return messages
