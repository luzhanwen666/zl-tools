"""
智能体引擎 - 执行器抽象基类

定义 AgentExecutionResult、BaseAgentExecutor，以及共享的
[USE_SKILL:X] 技能请求检测逻辑（所有 executor 共用）。
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from engine.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionResult:
    """Agent 执行结果 — 包含完整的思考追溯和中间状态"""

    content: str = ""
    thinking_trace: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    stage: str = "done"
    status_messages: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)

    def to_agent_message(self, agent_name: str = "") -> "AgentMessage":
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
                "skill_used": ", ".join(self.skills_used) if self.skills_used else None,
            },
        )


class BaseAgentExecutor(ABC):
    """Agent 执行器抽象基类"""

    def __init__(self, llm, tool_registry: "ToolRegistry | None" = None):
        self.llm = llm
        self.tool_registry = tool_registry

    @abstractmethod
    async def execute(
        self,
        agent: "AgentModel",
        user_message: str | None,
        context_messages: list,
        tools: list | None = None,
        system_prompt_override: str | None = None,
    ) -> AgentExecutionResult:
        ...

    # ── [USE_SKILL:X] 共享处理（供所有子类使用） ───────────────────

    async def _handle_skill_requests(
        self, response_text: str, agent: "AgentModel", react_messages: list[dict],
        status_messages: list[str], skills_used: list[str],
    ) -> bool:
        """
        检测 LLM 回复中的 [USE_SKILL:name]，加载 Layer 2 指令并注入到消息历史。

        返回 True 表示处理了一个或多个技能请求（下一轮 LLM 会基于指南继续）。
        """
        from engine.skills.loader import SkillsLoader, SKILL_TRIGGERS

        # 检测所有 [USE_SKILL:X] 标记
        requests = re.findall(r'\[USE_SKILL:\s*([^\]]+)\]', response_text, re.IGNORECASE)
        if not requests:
            return False

        loaded: list[str] = []
        for skill_name in requests:
            skill_name = skill_name.strip()
            if skill_name in loaded:
                continue

            # 匹配实际技能
            actual = SkillsLoader.detect_skill_request(
                f"[USE_SKILL:{skill_name}]", agent
            )
            if not actual:
                logger.warning("LLM requested unknown skill: %s", skill_name)
                continue

            # 加载 Layer 2 完整指令
            instruction = SkillsLoader.load_layer2_instruction(agent, actual)
            if not instruction:
                continue

            # 列出该技能的可执行脚本工具
            tools = await self._get_skill_tools(agent, actual)
            tool_list = ""
            if tools:
                tool_names = [t.name for t in tools]
                tool_list = (
                    f"\n\n## ⚡ 该技能的可执行脚本工具（已注册，请立即调用）\n"
                    + "\n".join(f"- 调用 `{n}` 执行脚本" for n in tool_names)
                )

            react_messages.append({
                "role": "user",
                "content": (
                    f"[技能「{actual}」完整操作指南已加载]\n\n"
                    f"{instruction}"
                    f"{tool_list}"
                    f"\n\n⚠️ 现在你已经有了完整指南和可调用工具。"
                    f"请立即使用 JSON 格式调用对应工具开始执行任务，不要再请求技能。"
                ),
            })
            status_messages.append(f"已加载技能: {actual} (含 {len(tools)} 个脚本工具)")
            skills_used.append(actual)
            loaded.append(actual)
            logger.info("Skill '%s' loaded for agent %s (%d tools)",
                       actual, agent.name, len(tools))

        return True

    async def _get_skill_tools(self, agent: "AgentModel", skill_name: str):
        """获取技能对应的已注册工具列表"""
        if not self.tool_registry:
            return []
        from engine.tools.registry import _get_skill_script_tools
        all_tools = _get_skill_script_tools(agent)
        prefix = f"skill_{skill_name.lower().replace('-','_').replace(' ','_')}_"
        return [t for t in all_tools if t.name.startswith(prefix)]
