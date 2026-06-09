"""
智能体引擎 - 群聊管理器

Round-Robin 多 Agent 协作：协调者分配任务 → 专家依次发言 → 全部发言后总结。
prompt 层控制协调者只说一句话，代码层保证所有专家发言后才接受 [FINISH]。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

from asgiref.sync import sync_to_async

from .agent_runner import AgentRunner, _is_finish_signal
from .schemas import AgentMessage, GroupChatState
from .tools.base import ToolRegistry
from .tools.registry import get_tools_for_agent_async
from .prompts import COORDINATOR_FIRST_PROMPT, EXPERT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from chat.models import ChatSession

logger = logging.getLogger(__name__)


@sync_to_async
def _load_agent_group(session: "ChatSession") -> list["AgentModel"]:
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
        self._prompt_overrides: dict[str, str] = {}

    async def run(self, session: "ChatSession", user_message: str) -> list[AgentMessage]:
        agent_group = await _load_agent_group(session)
        if not agent_group:
            return [AgentMessage(role="assistant", content="[错误] 未找到可用的 Agent 团队")]
        coordinator = next((a for a in agent_group if a.role == "coordinator"), agent_group[0])
        return await self.run_with_agents(session, user_message, agent_group, coordinator.name)

    async def run_stream(
        self, session: "ChatSession", user_message: str
    ) -> AsyncGenerator[AgentMessage, None]:
        agent_group = await _load_agent_group(session)
        if not agent_group:
            yield AgentMessage(role="assistant", content="[错误] 未找到可用的 Agent 团队")
            return
        coordinator = next((a for a in agent_group if a.role == "coordinator"), agent_group[0])
        async for msg in self.run_stream_with_agents(
            session, user_message, agent_group, coordinator.name
        ):
            yield msg

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

        await self._build_prompt_overrides(agent_list)
        state = GroupChatState(
            speakers=[a.name for a in agent_list if a.llm_config],
            speaker_roles={a.name: a.role for a in agent_list},
        )
        await _load_chat_history(session, state)
        state.add_message(AgentMessage(role="user", content=user_message, name="用户"))

        return await self._run_loop(agent_list, state)

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

        await self._build_prompt_overrides(agent_list)
        state = GroupChatState(
            speakers=[a.name for a in agent_list if a.llm_config],
            speaker_roles={a.name: a.role for a in agent_list},
        )
        await _load_chat_history(session, state)
        state.add_message(AgentMessage(role="user", content=user_message, name="用户"))

        agents_spoken: set[str] = set()
        expert_names = {a.name for a in agent_list if a.role != "coordinator"}

        while state.should_continue:
            speaker_name = state.get_current_speaker()
            if not speaker_name:
                break

            speaker_agent = next((a for a in agent_list if a.name == speaker_name), None)
            if not speaker_agent or not speaker_agent.llm_config:
                state.advance_speaker()
                continue

            tools = await get_tools_for_agent_async(speaker_agent, self.tool_registry)
            enhanced_prompt = self._prompt_overrides.get(speaker_name, speaker_agent.system_prompt or "")
            runner = AgentRunner(llm=speaker_agent.llm_config, tool_registry=self.tool_registry)

            try:
                response = await runner.run(
                    agent=speaker_agent,
                    group_messages=state.get_recent_messages(20),
                    tools=tools if tools else None,
                    system_prompt_override=enhanced_prompt,
                )
            except Exception as e:
                response = AgentMessage(
                    role="assistant",
                    content=f"[执行错误] {speaker_name}: {e}",
                    name=speaker_name,
                )

            state.add_message(response)
            agents_spoken.add(speaker_name)
            yield response

            # [FINISH] 只在所有专家都至少发言一次后生效
            all_experts_spoken = expert_names and expert_names.issubset(agents_spoken)
            if _is_finish_signal(response.content) and all_experts_spoken:
                break

            state.advance_speaker()

    async def _run_loop(self, agent_list: list["AgentModel"], state: GroupChatState) -> list[AgentMessage]:
        """非流式版本的主循环"""
        agents_spoken: set[str] = set()
        expert_names = {a.name for a in agent_list if a.role != "coordinator"}
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
            enhanced_prompt = self._prompt_overrides.get(speaker_name, speaker_agent.system_prompt or "")
            runner = AgentRunner(llm=speaker_agent.llm_config, tool_registry=self.tool_registry)

            try:
                response = await runner.run(
                    agent=speaker_agent,
                    group_messages=state.get_recent_messages(20),
                    tools=tools if tools else None,
                    system_prompt_override=enhanced_prompt,
                )
            except Exception as e:
                response = AgentMessage(
                    role="assistant",
                    content=f"[执行错误] {speaker_name}: {e}",
                    name=speaker_name,
                )

            state.add_message(response)
            all_messages.append(response)
            agents_spoken.add(speaker_name)

            all_experts_spoken = expert_names and expert_names.issubset(agents_spoken)
            if _is_finish_signal(response.content) and all_experts_spoken:
                break

            state.advance_speaker()

        return all_messages

    def _pick_coordinator(
        self, agent_list: list["AgentModel"], coordinator_name: str | None
    ) -> "AgentModel | None":
        if coordinator_name:
            return next((a for a in agent_list if a.name == coordinator_name), None)
        return next((a for a in agent_list if a.role == "coordinator"), agent_list[0])

    async def _build_prompt_overrides(self, agent_group: list["AgentModel"]):
        """为每个 Agent 构建增强 system_prompt。"""
        self._prompt_overrides.clear()
        members_desc = "\n".join(
            f"- {a.name}（{a.get_role_display() if hasattr(a, 'get_role_display') else a.role}）"
            for a in agent_group
        )
        # 构建团队技能目录给协调者
        skills_catalog = await _build_team_skills_catalog(agent_group)

        for agent in agent_group:
            base = agent.system_prompt or ""
            if agent.role == "coordinator":
                extra = COORDINATOR_FIRST_PROMPT.format(
                    agent_name=agent.name,
                    members_desc=members_desc,
                    skills_catalog=skills_catalog,
                )
            else:
                skills_text = await _build_skills_prompt(agent)
                tools_desc = "暂无"
                if self.tool_registry:
                    tools_list = await get_tools_for_agent_async(agent, self.tool_registry)
                    if tools_list:
                        tools_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools_list)
                extra = EXPERT_SYSTEM_PROMPT.format(
                    agent_name=agent.name, role="专家",
                    members_desc=members_desc,
                    expertise=agent.description or "通用分析",
                    tools_desc=tools_desc,
                )
                if skills_text:
                    extra += "\n\n" + skills_text
            self._prompt_overrides[agent.name] = (base + "\n\n" + extra) if base else extra


@sync_to_async
def _build_team_skills_catalog(agent_group: list["AgentModel"]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for agent in agent_group:
        for skill in agent.skills.filter(is_active=True):
            if skill.name not in seen:
                seen.add(skill.name)
                lines.append(f"- **{skill.name}**（绑定于 {agent.name}）：{skill.description or '通用技能'}")
    return "\n".join(lines) if lines else "（团队暂无注册技能）"


@sync_to_async
def _build_skills_prompt(agent: "AgentModel") -> str:
    skills = agent.skills.filter(is_active=True)
    if not skills.exists():
        return ""
    parts = ["## 技能操作规范（按步骤执行，不需要调用技能工具）"]
    for s in skills:
        section = f"### {s.name}\n{s.instruction}"
        if s.script_dir:
            section += f"\n\n**脚本目录**: `{s.script_dir}`"
        if s.allowed_tools:
            section += f"\n**可用工具**: {s.allowed_tools}"
        parts.append(section)
    return "\n\n".join(parts)


@sync_to_async
def _load_chat_history(session: "ChatSession", state: "GroupChatState"):
    from chat.models import ChatMessage
    recent = ChatMessage.objects.filter(session=session).order_by("-created_at")[:9]
    for msg in reversed(list(recent)[1:]):
        if msg.role not in ("assistant", "user"):
            continue
        content = msg.content
        if len(content) > 2000:
            content = content[:2000] + "...(截断)"
        state.add_message(AgentMessage(role=msg.role, content=content, name=msg.agent_name or ""))
