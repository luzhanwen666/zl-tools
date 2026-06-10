"""
智能体引擎 - 全局编排器

核心编排逻辑：独立分析 → 统一总结。
每位专家完整独立执行其分析（ReAct/Reflection/PlanAndSolve），
协调者在所有专家完成后一次性总结，不进行轮询群聊讨论。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

from asgiref.sync import sync_to_async

from .schemas import AgentMessage
from .tools.base import ToolRegistry
from .tools.registry import get_tools_for_agent_async
from .executors import get_executor, AgentExecutionResult
from . import prompts as _prompts

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel
    from chat.models import ChatSession, AgentPipeline

logger = logging.getLogger(__name__)


def load_layer1_safe(agent: "AgentModel") -> str:
    """安全加载 Layer 1 元数据（捕获 ImportError）"""
    try:
        from engine.skills.loader import SkillsLoader
        return SkillsLoader.load_layer1_metadata(agent)
    except Exception:
        return ""


# ── 同步 ORM 辅助 ───────────────────────────────────────────────────


@sync_to_async
def _get_pipeline(session: "ChatSession") -> "AgentPipeline | None":
    """获取会话关联的活跃流水线配置"""
    from chat.models import AgentPipeline
    return AgentPipeline.objects.filter(session=session, is_active=True).first()


# ── 编排器 ──────────────────────────────────────────────────────────


class GlobalOrchestrator:
    """
    全局编排器 — 独立分析 + 总结模式。

    与 GroupChatManager（轮询讨论）的关键区别：
    - 每个专家运行完整的执行策略（不是"一轮发言"）
    - 协调者在专家分析期间不插话
    - 所有专家完成后，协调者一次性总结
    - 支持前端配置流水线（串行/并行/依赖关系）
    """

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    # ── 公共接口 ─────────────────────────────────────────────────

    async def run(
        self,
        session: "ChatSession",
        user_message: str,
        agent_list: list["AgentModel"],
        global_agent: "AgentModel",
        pipeline: "AgentPipeline | None" = None,
    ) -> list[AgentMessage]:
        """非流式执行"""
        all_msgs: list[AgentMessage] = []

        coordinator = self._find_coordinator(agent_list, global_agent)
        experts = [a for a in agent_list if a.role != "coordinator" and a.llm_config]

        if not experts:
            return [AgentMessage(
                role="assistant", content="[错误] 没有可用的专家智能体",
                name=global_agent.name,
            )]

        # 解析流水线步骤顺序
        steps = await self._resolve_steps(pipeline, experts)

        # 1. 协调者分配任务
        task_msg = await self._assign_task(coordinator, user_message, experts)
        all_msgs.append(task_msg)

        # 2. 专家独立执行
        expert_msgs = await self._run_experts(experts, user_message, task_msg, steps)
        all_msgs.extend(expert_msgs)

        # 3. 协调者综合总结
        synthesis = await self._synthesize(coordinator, user_message, expert_msgs)
        all_msgs.append(synthesis)

        return all_msgs

    async def run_stream(
        self,
        session: "ChatSession",
        user_message: str,
        agent_list: list["AgentModel"],
        global_agent: "AgentModel",
        pipeline: "AgentPipeline | None" = None,
    ) -> AsyncGenerator[dict, None]:
        """流式执行 — yield SSE 事件字典"""
        coordinator = self._find_coordinator(agent_list, global_agent)
        experts = [a for a in agent_list if a.role != "coordinator" and a.llm_config]

        if not experts:
            yield {"type": "error", "content": "没有可用的专家智能体"}
            return

        steps = await self._resolve_steps(pipeline, experts)

        # 1. 分配任务
        yield {"type": "status", "agent_name": coordinator.name,
               "content": f"正在为 {len(experts)} 位专家分配任务..."}
        task_msg = await self._assign_task(coordinator, user_message, experts)
        yield {"type": "assistant", "content": task_msg.content,
               "agent_name": task_msg.name, "role": "coordinator"}

        # 2. 专家执行（逐步 yield 思考/工具调用/最终回复）
        expert_msgs: list[AgentMessage] = []
        async for event in self._run_experts_stream(experts, user_message, task_msg, steps):
            yield event
            if event.get("type") == "assistant":
                expert_msgs.append(AgentMessage(
                    role="assistant", content=event["content"],
                    name=event.get("agent_name", ""),
                    metadata=event.get("metadata", {}),
                ))

        # 3. 总结
        yield {"type": "status", "agent_name": coordinator.name,
               "content": "正在综合专家分析结果..."}
        synthesis = await self._synthesize(coordinator, user_message, expert_msgs)
        yield {"type": "assistant", "content": synthesis.content,
               "agent_name": synthesis.name, "role": "coordinator",
               "metadata": synthesis.metadata}
        yield {"type": "done"}

    # ── 内部方法 ─────────────────────────────────────────────────

    def _find_coordinator(self, agent_list: list["AgentModel"], global_agent: "AgentModel") -> "AgentModel":
        """找到协调者 Agent"""
        coord = next((a for a in agent_list if a.role == "coordinator" and a.llm_config), None)
        return coord or global_agent

    async def _resolve_steps(
        self, pipeline: "AgentPipeline | None", experts: list["AgentModel"]
    ) -> list[dict]:
        """解析执行步骤：优先使用流水线配置，否则按列表顺序串行"""
        if pipeline and pipeline.steps:
            # 验证 steps 中的 agent_name 在 experts 中
            valid_steps = []
            for s in pipeline.steps:
                if any(e.name == s.get("agent_name") for e in experts):
                    valid_steps.append(s)
            if valid_steps:
                return valid_steps

        # 默认：所有专家按列表顺序串行
        return [
            {"agent_name": e.name, "order": i, "depends_on": [], "mode": "sequential"}
            for i, e in enumerate(experts)
        ]

    async def _assign_task(
        self, coordinator: "AgentModel", user_message: str, experts: list["AgentModel"]
    ) -> AgentMessage:
        """协调者为每位专家分配任务"""
        expert_list = "\n".join(
            f"- **{e.name}**（{e.get_role_display() if hasattr(e, 'get_role_display') else e.role}）"
            for e in experts
        )

        task_prompt = _prompts.COORDINATOR_ORCHESTRATE_PROMPT.format(
            agent_name=coordinator.name,
            experts_desc=expert_list,
            user_question=user_message,
        )

        messages = [{"role": "user", "content": task_prompt}]
        try:
            from . import llm_client as llm_module
            response = await llm_module.llm_client.chat(
                provider=coordinator.llm_config.provider,
                model_id=coordinator.llm_config.model_id,
                messages=messages,
                api_base=coordinator.llm_config.api_base,
                api_key=coordinator.llm_config.api_key,
                max_tokens=min(coordinator.llm_config.max_tokens, 1024),
                temperature=0.3,
            )
        except Exception as e:
            logger.exception("Task assignment failed")
            response = f"请各位专家针对以下问题进行分析：{user_message}"

        return AgentMessage(
            role="assistant", content=response,
            name=coordinator.name,
            metadata={"stage": "task_assignment"},
        )

    async def _run_experts(
        self,
        experts: list["AgentModel"],
        user_message: str,
        task_msg: AgentMessage,
        steps: list[dict],
    ) -> list[AgentMessage]:
        """依次执行所有专家"""
        results: list[AgentMessage] = []
        completed: set[str] = set()

        for step in steps:
            agent_name = step.get("agent_name", "")
            expert = next((e for e in experts if e.name == agent_name), None)
            if not expert:
                continue

            # 检查依赖
            deps = step.get("depends_on", [])
            if deps:
                # 等待所有依赖完成（当前为串行，依赖已自然满足）
                missing = [d for d in deps if d not in completed]
                if missing:
                    logger.warning("Expert %s depends on %s but they haven't run", agent_name, missing)

            result = await self._run_single_expert(expert, user_message, task_msg)
            results.append(result)
            completed.add(agent_name)

        return results

    async def _run_single_expert(
        self, expert: "AgentModel", user_message: str, task_msg: AgentMessage
    ) -> AgentMessage:
        """执行单个专家的完整分析 — 技能渐进式披露"""
        tools = await get_tools_for_agent_async(expert, self.tool_registry)

        # ── 技能：Layer 1 已注入 system prompt，LLM 自主 [USE_SKILL:X] 决定何时加载 Layer 2 ──
        system_prompt = self._build_expert_prompt(expert, user_message, tools)

        executor = get_executor(expert, tool_registry=self.tool_registry)

        try:
            result: AgentExecutionResult = await executor.execute(
                agent=expert,
                user_message=user_message,
                context_messages=[task_msg],
                tools=tools if tools else None,
                system_prompt_override=system_prompt,
            )
        except Exception as e:
            logger.exception("Expert %s execution failed", expert.name)
            return AgentMessage(
                role="assistant",
                content=f"[执行错误] {expert.name}: {str(e)}",
                name=expert.name,
            )

        msg = result.to_agent_message(expert.name)
        if not msg.metadata:
            msg.metadata = {}
        used = result.skills_used or []
        for t in result.thinking_trace:
            if t.get("skill_request") and t["skill_request"] not in used:
                used.append(t["skill_request"])
        msg.metadata["skill_used"] = ", ".join(used) if used else None
        return msg

    async def _run_experts_stream(
        self,
        experts: list["AgentModel"],
        user_message: str,
        task_msg: AgentMessage,
        steps: list[dict],
    ) -> AsyncGenerator[dict, None]:
        """流式执行所有专家"""
        completed: set[str] = set()

        for step in steps:
            agent_name = step.get("agent_name", "")
            expert = next((e for e in experts if e.name == agent_name), None)
            if not expert:
                continue

            yield {
                "type": "status", "agent_name": agent_name,
                "content": f"正在调用 {agent_name} 进行分析...",
            }

            # ── 技能：Layer 1 已注入，LLM 自主 [USE_SKILL:X] ──
            skill_name = None
            skill_instruction = ""

            # 执行并 yield 思考过程
            tools = await get_tools_for_agent_async(expert, self.tool_registry)
            system_prompt = self._build_expert_prompt(expert, user_message, tools)
            if skill_instruction:
                system_prompt += "\n\n" + skill_instruction
            executor = get_executor(expert, tool_registry=self.tool_registry)

            try:
                result: AgentExecutionResult = await executor.execute(
                    agent=expert,
                    user_message=user_message,
                    context_messages=[task_msg],
                    tools=tools if tools else None,
                    system_prompt_override=system_prompt,
                )

                # Yield 思考追溯
                for trace in result.thinking_trace:
                    if trace.get("steps"):
                        yield {
                            "type": "plan",
                            "agent_name": expert.name,
                            "steps": trace.get("steps", []),
                        }
                    elif trace.get("tool_calls"):
                        for tc in trace.get("tool_calls", []):
                            yield {
                                "type": "tool_call",
                                "agent_name": expert.name,
                                "tool": tc.get("tool", ""),
                                "args": tc.get("args", ""),
                            }
                    yield {
                        "type": "thinking",
                        "agent_name": expert.name,
                        "stage": trace.get("stage", ""),
                        "content": trace.get("content", "")[:500],
                    }

                # Yield 状态消息
                for sm in result.status_messages:
                    yield {"type": "status", "agent_name": expert.name, "content": sm}

                # Yield 最终回复
                yield {
                    "type": "assistant",
                    "content": result.content,
                    "agent_name": expert.name,
                    "role": "expert",
                    "metadata": {
                        "thinking": result.thinking_trace,
                        "stage": result.stage,
                        "tool_calls": result.tool_calls,
                        "agent_type": getattr(expert, "agent_type", "react"),
                        "skill_used": skill_name or None,
                        "skills_meta": load_layer1_safe(expert),
                    },
                }

            except Exception as e:
                logger.exception("Expert %s execution failed", expert.name)
                yield {
                    "type": "error",
                    "agent_name": expert.name,
                    "content": f"执行错误: {str(e)}",
                }

            completed.add(agent_name)

    async def _synthesize(
        self, coordinator: "AgentModel", user_message: str,
        expert_msgs: list[AgentMessage],
    ) -> AgentMessage:
        """协调者综合所有专家分析，给出最终答案"""
        if not expert_msgs:
            return AgentMessage(
                role="assistant",
                content="专家团队未能提供有效分析。",
                name=coordinator.name,
            )

        analyses_text = ""
        for i, msg in enumerate(expert_msgs):
            analyses_text += f"\n### {msg.name} 的分析\n{msg.content}\n"

        synthesis_prompt = _prompts.GLOBAL_SYNTHESIS_PROMPT.format(
            agent_name=coordinator.name,
            user_question=user_message,
            expert_analyses=analyses_text,
        )

        messages = [{"role": "user", "content": synthesis_prompt}]
        try:
            from . import llm_client as llm_module
            response = await llm_module.llm_client.chat(
                provider=coordinator.llm_config.provider,
                model_id=coordinator.llm_config.model_id,
                messages=messages,
                api_base=coordinator.llm_config.api_base,
                api_key=coordinator.llm_config.api_key,
                max_tokens=min(coordinator.llm_config.max_tokens, 4096),
                temperature=0.5,
            )
        except Exception as e:
            logger.exception("Synthesis failed")
            response = f"[综合总结失败: {e}]\n\n" + "\n\n---\n\n".join(
                f"**{m.name}**: {m.content[:500]}" for m in expert_msgs
            )

        return AgentMessage(
            role="assistant", content=response,
            name=coordinator.name,
            metadata={"stage": "synthesis"},
        )

    def _build_expert_prompt(self, expert: "AgentModel", user_message: str,
                             tools: list = None) -> str:
        """构建专家独立分析的增强 system prompt"""
        base = expert.system_prompt or ""
        expertise = expert.description or "通用分析"

        # 技能元数据（Layer 1）
        skills_meta = load_layer1_safe(expert)

        # 工具描述（真实可用工具列表）
        tools_desc = "请使用可用工具获取数据后再分析"
        if tools:
            tool_lines = []
            for t in tools[:12]:  # 最多列出12个，避免prompt过长
                desc = getattr(t, 'description', '') or ''
                if len(desc) > 80:
                    desc = desc[:80] + "..."
                tool_lines.append(f"- **{t.name}**: {desc}")
            if tool_lines:
                tools_desc = "\n".join(tool_lines)
                if len(tools) > 12:
                    tools_desc += f"\n> ...及其他 {len(tools)-12} 个工具"

        extra = _prompts.EXPERT_INDEPENDENT_PROMPT.format(
            agent_name=expert.name,
            role="专家",
            expertise=expertise,
            user_question=user_message,
            skills_meta=skills_meta,
            tools_desc=tools_desc,
        )

        return f"{base}\n\n{extra}" if base else extra
