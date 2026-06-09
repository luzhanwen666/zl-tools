"""
智能体引擎 - 群聊管理器

核心模块：控制多 Agent 群聊的发言权轮转、上下文共享和结束判定。

所有 Django ORM 操作通过 sync_to_async 包装，确保在 async 上下文中安全执行。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

from asgiref.sync import sync_to_async

from .agent_runner import AgentRunner, _is_finish_signal
from .schemas import AgentMessage, GroupChatState
from .tools.base import ToolRegistry
from .tools.registry import get_tools_for_agent_async
from .prompts import COORDINATOR_SYSTEM_PROMPT, EXPERT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from chat.models import ChatSession

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 同步辅助函数（sync_to_async 包装，供 async 上下文安全调用）
# ------------------------------------------------------------------

@sync_to_async
def _load_agent_group(session: "ChatSession") -> list["AgentModel"]:
    """通过 session.agent 的 group 字段找到同组所有成员。"""
    coordinator = session.agent
    if not coordinator:
        return []
    group_name = getattr(coordinator, "group", "default")
    from agents.models import Agent
    return list(Agent.objects.filter(group=group_name, is_active=True).order_by("-role"))


class GroupChatManager:
    """群聊管理器"""

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    # ------------------------------------------------------------------
    # 公共接口 — 自动发现模式（兼容旧调用）
    # ------------------------------------------------------------------

    async def run(self, session: "ChatSession", user_message: str) -> list[AgentMessage]:
        """执行一轮群聊讨论（自动从 session.agent 的 group 加载团队）。"""
        agent_group = await _load_agent_group(session)
        if not agent_group:
            return [AgentMessage(role="assistant", content="[错误] 未找到可用的 Agent 团队")]
        coordinator = next((a for a in agent_group if a.role == "coordinator"), agent_group[0])
        return await self.run_with_agents(session, user_message, agent_group, coordinator.name)

    async def run_stream(
        self, session: "ChatSession", user_message: str
    ) -> AsyncGenerator[AgentMessage, None]:
        """流式执行群聊（自动发现模式）。"""
        agent_group = await _load_agent_group(session)
        if not agent_group:
            yield AgentMessage(role="assistant", content="[错误] 未找到可用的 Agent 团队")
            return
        coordinator = next((a for a in agent_group if a.role == "coordinator"), agent_group[0])
        async for msg in self.run_stream_with_agents(
            session, user_message, agent_group, coordinator.name
        ):
            yield msg

    # ------------------------------------------------------------------
    # 公共接口 — 显式 Agent 列表模式（GlobalRouter 使用）
    # ------------------------------------------------------------------

    async def run_with_agents(
        self,
        session: "ChatSession",
        user_message: str,
        agent_list: list["AgentModel"],
        coordinator_name: str | None = None,
    ) -> list[AgentMessage]:
        if not agent_list:
            return [AgentMessage(role="assistant", content="[错误] Agent 列表为空")]

        coordinator = self._pick_coordinator(agent_list, coordinator_name)
        if not coordinator or not coordinator.llm_config:
            return [AgentMessage(role="assistant", content="[错误] 协调者未配置大模型")]

        state = GroupChatState(
            speakers=[a.name for a in agent_list if a.llm_config],
            speaker_roles={a.name: a.role for a in agent_list},
        )
        state.add_message(AgentMessage(role="user", content=user_message, name="用户"))
        await self._inject_team_prompts(agent_list, state)

        all_messages: list[AgentMessage] = []
        while state.should_continue:
            speaker_name = state.get_current_speaker()
            if not speaker_name:
                break

            speaker_agent = next((a for a in agent_list if a.name == speaker_name), None)
            if not speaker_agent or not speaker_agent.llm_config:
                state.advance_speaker()
                continue

            tools = await get_tools_for_agent_async(speaker_agent, self.tool_registry)
            runner = AgentRunner(llm=speaker_agent.llm_config, tool_registry=self.tool_registry)
            try:
                response = await runner.run(
                    agent=speaker_agent,
                    group_messages=state.get_recent_messages(20),
                    tools=tools if tools else None,
                )
            except Exception as e:
                logger.error("Agent %s execution failed: %s", speaker_name, e)
                response = AgentMessage(
                    role="assistant",
                    content=f"[执行错误] {speaker_name}: {e}",
                    name=speaker_name,
                )

            state.add_message(response)
            all_messages.append(response)

            if _is_finish_signal(response.content):
                state.is_finished = True
                break

            state.advance_speaker()

        return all_messages

    async def run_stream_with_agents(
        self,
        session: "ChatSession",
        user_message: str,
        agent_list: list["AgentModel"],
        coordinator_name: str | None = None,
    ) -> AsyncGenerator[AgentMessage, None]:
        if not agent_list:
            yield AgentMessage(role="assistant", content="[错误] Agent 列表为空")
            return

        coordinator = self._pick_coordinator(agent_list, coordinator_name)
        if not coordinator or not coordinator.llm_config:
            yield AgentMessage(role="assistant", content="[错误] 协调者未配置大模型")
            return

        state = GroupChatState(
            speakers=[a.name for a in agent_list if a.llm_config],
            speaker_roles={a.name: a.role for a in agent_list},
        )
        state.add_message(AgentMessage(role="user", content=user_message, name="用户"))
        await self._inject_team_prompts(agent_list, state)

        while state.should_continue:
            speaker_name = state.get_current_speaker()
            if not speaker_name:
                break

            speaker_agent = next((a for a in agent_list if a.name == speaker_name), None)
            if not speaker_agent or not speaker_agent.llm_config:
                state.advance_speaker()
                continue

            tools = await get_tools_for_agent_async(speaker_agent, self.tool_registry)
            runner = AgentRunner(llm=speaker_agent.llm_config, tool_registry=self.tool_registry)
            try:
                response = await runner.run(
                    agent=speaker_agent,
                    group_messages=state.get_recent_messages(20),
                    tools=tools if tools else None,
                )
            except Exception as e:
                response = AgentMessage(
                    role="assistant",
                    content=f"[执行错误] {speaker_name}: {e}",
                    name=speaker_name,
                )

            state.add_message(response)
            yield response

            if _is_finish_signal(response.content):
                state.is_finished = True
                break

            state.advance_speaker()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _pick_coordinator(
        self, agent_list: list["AgentModel"], coordinator_name: str | None
    ) -> "AgentModel | None":
        if coordinator_name:
            return next((a for a in agent_list if a.name == coordinator_name), None)
        return next((a for a in agent_list if a.role == "coordinator"), agent_list[0])

    async def _inject_team_prompts(self, agent_group: list["AgentModel"], state: GroupChatState):
        """为每个 Agent 注入团队信息到 system_prompt。"""
        members_desc = "\n".join(
            f"- {a.name}（{a.get_role_display() if hasattr(a, 'get_role_display') else a.role}）"
            for a in agent_group
        )
        for agent in agent_group:
            if agent.role == "coordinator":
                extra = COORDINATOR_SYSTEM_PROMPT.format(
                    agent_name=agent.name, role="协调者", members_desc=members_desc,
                )
            else:
                tools_desc = "暂无"
                if self.tool_registry:
                    tools_list = await get_tools_for_agent_async(agent, self.tool_registry)
                    if tools_list:
                        tools_desc = "\n".join(
                            f"- {t.name}: {t.description}" for t in tools_list
                        )
                extra = EXPERT_SYSTEM_PROMPT.format(
                    agent_name=agent.name,
                    role="专家",
                    members_desc=members_desc,
                    expertise=agent.description or "通用分析",
                    tools_desc=tools_desc,
                )
            if not agent.system_prompt:
                agent.system_prompt = extra
            else:
                agent.system_prompt = agent.system_prompt + "\n\n" + extra
