"""
智能体引擎 - 全局智能体路由器

核心模块：全局 Agent 接收用户输入 → 问题分类 → 智能路由到专家 → 协作执行 → 结果合成。

所有 Django ORM 操作通过 sync_to_async 包装，确保在 async 上下文中安全执行。
"""

from __future__ import annotations

import json
import logging
import re
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
    ).prefetch_related("skills", "mcp_tools")

    if not other_agents:
        return "（暂无其他可用专家）"

    lines = []
    for ag in other_agents:
        desc = ag.description or "通用智能体"
        role_label = {"coordinator": "协调者", "expert": "专家", "member": "成员"}.get(
            ag.role, ag.role
        )
        type_label = {
            "react": "ReAct", "simple": "Simple",
            "reflection": "Reflection", "plan_and_solve": "Plan&Solve",
        }.get(ag.agent_type or "react", "ReAct")

        # 附加技能信息
        skills_str = ""
        skills = [s for s in ag.skills.all() if s.is_active]
        if skills:
            skill_names = ", ".join(s.name for s in skills[:3])
            if len(skills) > 3:
                skill_names += f" 等{len(skills)}项"
            skills_str = f" · 技能: {skill_names}"

        # 附加 MCP 工具信息
        mcp_str = ""
        mcp_tools = [m for m in ag.mcp_tools.all() if m.is_active]
        if mcp_tools:
            mcp_names = ", ".join(m.name for m in mcp_tools[:2])
            if len(mcp_tools) > 2:
                mcp_names += f" 等{len(mcp_tools)}项"
            mcp_str = f" · 外部工具: {mcp_names}"

        lines.append(
            f"- **{ag.name}**（{role_label}·{type_label}{skills_str}{mcp_str}）：{desc}"
        )

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
        manual_agents: list["AgentModel"] | None = None,
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

        # 2. 路由决策：手动优先，否则自动分类
        if manual_agents:
            # 手动模式：直接使用已解析的 Agent 对象（视图层已做 ORM）
            logger.info("Manual agents: %s", [a.name for a in manual_agents])
            route_result = RouteResult(
                intent="手动指定",
                recommended_agents=[a.name for a in manual_agents],
                is_general_question=not manual_agents,
                reasoning="用户手动选择专家",
            )
            expert_agents = manual_agents  # 直接使用，无需 ORM 解析
        else:
            route_result = await self.classify(user_message, global_agent)
            logger.info("Route result: %s", route_result)

        # 3. 路由 + 执行
        if route_result.is_general_question or not route_result.recommended_agents:
            # 无匹配专家 → 关键词兜底强制匹配
            logger.info("No expert matched — forcing keyword fallback")
            fallback = prompts.keyword_fallback_match(user_message, await _build_agents_catalog(global_agent))
            if fallback:
                route_result.recommended_agents = fallback
                route_result.is_general_question = False
            else:
                return [AgentMessage(
                    role="assistant",
                    content="⚠️ 未找到匹配的专家，请手动选择专家或创建群组配置自动路由。",
                    name="全局智能体",
                )]

        if not route_result.is_general_question and route_result.recommended_agents:
            logger.info("Routing to expert agents: %s", route_result.recommended_agents)
            # 手动模式下 expert_agents 已在上面设置好（Agent对象），自动模式需要 ORM 解析
            if not manual_agents:
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

            # 使用 GlobalOrchestrator（独立分析 + 总结）替代 GroupChatManager（轮询群聊）
            from .orchestrator import GlobalOrchestrator
            orchestrator = GlobalOrchestrator(tool_registry=self.tool_registry)
            orc_messages = await orchestrator.run(
                session, user_message, agent_list, global_agent,
            )
            all_messages.extend(orc_messages)

        return all_messages

    async def run_stream(
        self,
        session: "ChatSession",
        user_message: str,
        manual_agents: list["AgentModel"] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """流式执行 — 使用 GlobalOrchestrator 的独立分析+总结模式"""
        global_agent = await _get_global_agent()
        if not global_agent or not global_agent.llm_config:
            yield {"type": "error", "content": "全局智能体未配置大模型，请联系管理员。"}
            return

        # 手动指定专家 → 跳过分类，直接编排
        if manual_agents:
            expert_names = [a.name for a in manual_agents]
            yield {"type": "routing", "status": "manual",
                   "content": f"已手动选择专家：{', '.join(expert_names)}"}
            agent_list = [global_agent] + manual_agents
            from .orchestrator import GlobalOrchestrator
            orchestrator = GlobalOrchestrator(tool_registry=self.tool_registry)
            async for event in orchestrator.run_stream(
                session, user_message, agent_list, global_agent
            ):
                yield event
            return

        # 自动分类模式
        yield {"type": "routing", "status": "classifying", "content": "正在分析您的问题..."}

        route_result = await self.classify(user_message, global_agent)

        if route_result.is_general_question or not route_result.recommended_agents:
            # 无匹配专家 → 关键词兜底强制匹配
            fallback = prompts.keyword_fallback_match(user_message, await _build_agents_catalog(global_agent))
            if fallback:
                route_result.recommended_agents = [a.name for a in await _resolve_agents(fallback)]
                route_result.is_general_question = False
                yield {
                    "type": "routing", "status": "matched",
                    "content": f"已匹配专家：{', '.join(route_result.recommended_agents)}（关键词匹配）",
                    "agents": route_result.recommended_agents,
                }
            else:
                yield {
                    "type": "routing", "status": "unmatched",
                    "content": "未找到匹配的专家",
                }
                yield {
                    "type": "assistant",
                    "content": "⚠️ 未找到匹配的专家，请手动选择专家或创建群组配置自动路由。",
                    "agent_name": "全局智能体",
                }
                yield {"type": "done"}
                return

        if not route_result.is_general_question and route_result.recommended_agents:
            # 匹配到专家 → 使用 GlobalOrchestrator 流式执行
            expert_agents = await _resolve_agents(route_result.recommended_agents)
        agent_names = [a.name for a in expert_agents]

        yield {
            "type": "routing", "status": "matched",
            "content": f"已激活专家：{', '.join(agent_names)}",
            "intent": route_result.intent,
            "reasoning": route_result.reasoning[:60],
            "agents": agent_names,
        }

        agent_list = [global_agent] + expert_agents
        from .orchestrator import GlobalOrchestrator
        orchestrator = GlobalOrchestrator(tool_registry=self.tool_registry)

        async for event in orchestrator.run_stream(
            session, user_message, agent_list, global_agent
        ):
            yield event

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------

    async def classify(self, user_message: str, global_agent: "AgentModel") -> RouteResult:
        """让全局 Agent 分析用户意图并做出路由决策。

        分类流程：
        1. LLM 分类（system prompt 强约束）
        2. 如果 LLM 返回 is_general_question=true 或解析失败 → 关键词兜底匹配
        """
        agents_catalog = await _build_agents_catalog(global_agent)

        messages = prompts.build_classifier_messages(
            agent_name=global_agent.name,
            agents_catalog=agents_catalog,
            user_message=user_message,
        )

        # ── 步骤 1: LLM 分类 ──
        try:
            from . import llm_client as llm_module
            llm_config = global_agent.llm_config
            response = await llm_module.llm_client.chat(
                provider=llm_config.provider,
                model_id=llm_config.model_id,
                messages=messages,
                api_base=llm_config.api_base,
                api_key=llm_config.api_key,
                max_tokens=min(llm_config.max_tokens, 512),
                temperature=0.0,  # 零温度 = 最高确定性
            )
        except Exception as e:
            logger.exception("Classification LLM call failed")
            # LLM 调用失败 → 直接走关键词兜底
            fallback = prompts.keyword_fallback_match(user_message, agents_catalog)
            logger.info("LLM classification failed, keyword fallback: %s", fallback)
            return RouteResult(
                intent="关键词匹配（LLM不可用）",
                recommended_agents=fallback,
                is_general_question=not bool(fallback),
                reasoning=f"LLM调用失败，自动关键词匹配",
                raw_response=str(e),
            )

        # ── 步骤 2: 解析 LLM 输出 ──
        result = self._parse_classification_with_fallback(
            response, user_message, agents_catalog
        )
        return result

    def _parse_classification_with_fallback(
        self, response: str, user_message: str, agents_catalog: str
    ) -> RouteResult:
        """解析 LLM 分类 JSON。

        如果 LLM 返回 is_general_question=true，但用户消息明显包含专业内容，
        则自动触发关键词兜底匹配。
        """
        json_objects = _extract_json_objects(response)

        for obj_str in json_objects:
            try:
                data = json.loads(obj_str)
                if "is_general_question" in data or "intent" in data:
                    is_general = data.get("is_general_question", True)
                    recommended = data.get("recommended_agents", [])
                    intent = data.get("intent", "")
                    reasoning = data.get("reasoning", "")

                    # LLM 判定为通用问题 / 没推荐专家 → 直接用全部可用专家
                    if is_general or not recommended:
                        all_names = re.findall(r'\*\*(.+?)\*\*', agents_catalog)
                        if all_names:
                            logger.info("LLM returned is_general_question=true, using all %d agents", len(all_names))
                            return RouteResult(
                                intent=f"LLM未匹配→使用全部{len(all_names)}位专家",
                                recommended_agents=all_names,
                                is_general_question=False,
                                reasoning=f"LLM判定通用问题，自动启用全部专家",
                                raw_response=response,
                            )

                    # LLM 正确分类
                    logger.info("LLM classified: intent=%s agents=%s", intent, recommended)
                    return RouteResult(
                        intent=intent,
                        recommended_agents=recommended,
                        is_general_question=is_general,
                        reasoning=reasoning,
                        raw_response=response,
                    )
            except (json.JSONDecodeError, TypeError):
                continue

        # JSON 解析失败 → 关键词兜底
        logger.warning("Failed to parse classification JSON from: %s", response[:300])
        fallback = prompts.keyword_fallback_match(user_message, agents_catalog)
        logger.info("JSON parse failed, keyword fallback: %s", fallback)
        return RouteResult(
            intent="关键词匹配（LLM格式异常）",
            recommended_agents=fallback,
            is_general_question=not bool(fallback),
            reasoning="LLM输出格式异常，自动使用关键词匹配",
            raw_response=response,
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
