"""
智能体引擎 - 全局智能体路由器

核心模块：全局 Agent 接收用户输入 → 问题分类 → 智能路由到专家 → 协作执行 → 结果合成。

所有 Django ORM 操作通过 sync_to_async 包装，确保在 async 上下文中安全执行。
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, TYPE_CHECKING

from asgiref.sync import sync_to_async

from .agent_runner import AgentRunner, _extract_json_objects
from .schemas import AgentMessage
from .tools.base import ToolRegistry
from . import router_prompts as prompts

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from chat.models import ChatSession

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 同步 ORM 操作（用 sync_to_async 包装后在 async 上下文中安全调用）
# ------------------------------------------------------------------

@sync_to_async
def _get_global_agent():
    """获取全局智能体（sync，被 sync_to_async 包装）"""
    from agents.models import Agent
    return Agent.objects.filter(is_global=True, is_active=True).select_related("llm_config").first()


@sync_to_async
def _build_agents_catalog(global_agent: "AgentModel") -> str:
    """构建可用专家 Agent 的能力目录（sync）"""
    from agents.models import Agent

    other_agents = Agent.objects.filter(is_active=True).exclude(
        pk=global_agent.pk
    ).values("name", "role", "description")

    if not other_agents:
        return "（暂无其他可用专家，请由你直接回答所有问题）"

    lines = []
    for ag in other_agents:
        desc = ag["description"] or "通用智能体"
        role_label = {"coordinator": "协调者", "expert": "专家", "member": "成员"}.get(
            ag["role"], ag["role"]
        )
        lines.append(f"- **{ag['name']}**（{role_label}）：{desc}")

    return "\n".join(lines)


@sync_to_async
def _resolve_agents(names: list[str]) -> list["AgentModel"]:
    """根据名称列表查找 Agent，预加载 skills 和 mcp_tools 避免懒查询（sync）"""
    from agents.models import Agent

    agents = []
    for name in names:
        agent = (
            Agent.objects
            .filter(name__iexact=name, is_active=True)
            .select_related("llm_config")
            .prefetch_related("skills", "mcp_tools")
            .first()
        )
        if agent:
            agents.append(agent)
        else:
            logger.warning("Recommended agent not found: %s", name)
    return agents


class RouteResult:
    """路由决策结果"""

    def __init__(
        self,
        intent: str = "",
        recommended_agents: list[str] | None = None,
        is_general_question: bool = True,
        reasoning: str = "",
        raw_response: str = "",
    ):
        self.intent = intent
        self.recommended_agents = recommended_agents or []
        self.is_general_question = is_general_question
        self.reasoning = reasoning
        self.raw_response = raw_response

    def __repr__(self):
        return (
            f"RouteResult(intent={self.intent!r}, agents={self.recommended_agents}, "
            f"is_general={self.is_general_question})"
        )


class GlobalRouter:
    """全局智能体路由器 — 问题分类 + 智能分发 + 结果合成"""

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def run(
        self,
        session: "ChatSession",
        user_message: str,
    ) -> list[AgentMessage]:
        all_messages: list[AgentMessage] = []

        # 1. 加载全局 Agent（sync_to_async 包装）
        global_agent = await _get_global_agent()
        if not global_agent or not global_agent.llm_config:
            return [AgentMessage(
                role="assistant",
                content="[错误] 全局智能体未配置大模型，请联系管理员。",
                name="系统",
            )]

        # 2. 分类
        route_result = await self.classify(user_message, global_agent)
        logger.info("Route result: %s", route_result)

        # 3. 路由 + 执行
        if route_result.is_general_question or not route_result.recommended_agents:
            logger.info("Routing to global agent direct response")
            msg = await self._run_direct(global_agent, user_message)
            all_messages.append(msg)
        else:
            logger.info("Routing to expert agents: %s", route_result.recommended_agents)
            expert_agents = await _resolve_agents(route_result.recommended_agents)
            agent_list = [global_agent] + expert_agents

            routing_msg = AgentMessage(
                role="system",
                content=(
                    f"🔍 分析意图：{route_result.intent}\n"
                    f"📋 激活专家：{', '.join(a.name for a in expert_agents) if expert_agents else '无'}\n"
                    f"💡 分析理由：{route_result.reasoning}"
                ),
                name="全局智能体",
            )
            all_messages.append(routing_msg)

            # 执行群聊（群聊内已用 sync_to_async 处理 ORM）
            from .group_chat import GroupChatManager
            manager = GroupChatManager(tool_registry=self.tool_registry)
            chat_messages = await manager.run_with_agents(
                session, user_message, agent_list, global_agent.name
            )
            all_messages.extend(chat_messages)

        return all_messages

    async def run_stream(
        self,
        session: "ChatSession",
        user_message: str,
    ) -> AsyncGenerator[dict, None]:
        global_agent = await _get_global_agent()
        if not global_agent or not global_agent.llm_config:
            yield {"type": "error", "content": "全局智能体未配置大模型，请联系管理员。"}
            return

        yield {"type": "routing", "status": "classifying", "content": "正在分析您的问题..."}

        route_result = await self.classify(user_message, global_agent)

        if route_result.is_general_question or not route_result.recommended_agents:
            yield {
                "type": "routing", "status": "direct",
                "content": "由全局智能体直接回答", "intent": route_result.intent,
            }
            msg = await self._run_direct(global_agent, user_message)
            yield {"type": "assistant", "content": msg.content, "agent_name": msg.name}
        else:
            expert_agents = await _resolve_agents(route_result.recommended_agents)
            agent_names = [a.name for a in expert_agents]

            yield {
                "type": "routing", "status": "matched",
                "content": f"已激活专家：{', '.join(agent_names)}",
                "intent": route_result.intent,
                "reasoning": route_result.reasoning,
                "agents": agent_names,
            }

            agent_list = [global_agent] + expert_agents
            from .group_chat import GroupChatManager
            manager = GroupChatManager(tool_registry=self.tool_registry)

            async for msg in manager.run_stream_with_agents(
                session, user_message, agent_list, global_agent.name
            ):
                yield {"type": "assistant", "content": msg.content, "agent_name": msg.name}

        yield {"type": "done"}

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------

    async def classify(self, user_message: str, global_agent: "AgentModel") -> RouteResult:
        """让全局 Agent 分析用户意图并做出路由决策。"""
        # 构建可用 Agent 目录（sync_to_async 包装）
        agents_catalog = await _build_agents_catalog(global_agent)

        messages = prompts.build_classifier_messages(
            agent_name=global_agent.name,
            agents_catalog=agents_catalog,
            user_message=user_message,
        )

        try:
            from . import llm_client as llm_module
            llm_config = global_agent.llm_config
            response = await llm_module.llm_client.chat(
                provider=llm_config.provider,
                model_id=llm_config.model_id,
                messages=messages,
                api_base=llm_config.api_base,
                api_key=llm_config.api_key,
                max_tokens=min(llm_config.max_tokens, 1024),
                temperature=0.3,
            )
        except Exception as e:
            logger.exception("Classification LLM call failed")
            return RouteResult(
                intent="分类失败", is_general_question=True,
                reasoning=f"LLM调用失败: {e}", raw_response="",
            )

        return self._parse_classification(response)

    def _parse_classification(self, response: str) -> RouteResult:
        """解析 LLM 返回的分类 JSON"""
        json_objects = _extract_json_objects(response)
        for obj_str in json_objects:
            try:
                data = json.loads(obj_str)
                if "is_general_question" in data or "intent" in data:
                    return RouteResult(
                        intent=data.get("intent", ""),
                        recommended_agents=data.get("recommended_agents", []),
                        is_general_question=data.get("is_general_question", True),
                        reasoning=data.get("reasoning", ""),
                        raw_response=response,
                    )
            except (json.JSONDecodeError, TypeError):
                continue

        logger.warning("Failed to parse classification from: %s", response[:200])
        return RouteResult(
            intent="未分类", is_general_question=True,
            reasoning="无法解析分类结果，降级为直接回复", raw_response=response,
        )

    async def _run_direct(self, global_agent: "AgentModel", user_message: str) -> AgentMessage:
        """全局 Agent 直接回复（无需群聊）。工具列表需 sync_to_async 加载。"""
        from .agent_runner import AgentRunner
        from .tools.registry import get_tools_for_agent_async

        runner = AgentRunner(llm=global_agent.llm_config, tool_registry=self.tool_registry)
        tools = await get_tools_for_agent_async(global_agent, self.tool_registry)

        try:
            return await runner.run(
                agent=global_agent, group_messages=[],
                tools=tools if tools else None,
            )
        except Exception as e:
            logger.exception("Direct response failed")
            return AgentMessage(
                role="assistant", content=f"[错误] 回复生成失败: {e}",
                name=global_agent.name,
            )
