"""
智能体引擎 - 群组拓扑执行器

从 AgentGroup 的 Start 节点出发，沿 GroupEdge 遍历拓扑执行。
支持的节点类型：start / agent / condition / loop / parallel / merge / end
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, TYPE_CHECKING

from .schemas import AgentMessage
from .executors import get_executor
from .tools.base import ToolRegistry
from .tools.registry import get_tools_for_agent_async

if TYPE_CHECKING:
    from agents.models import Agent, AgentGroup, GroupNode, GroupEdge
    from chat.models import ChatSession

logger = logging.getLogger(__name__)


async def load_topology(group: "AgentGroup") -> tuple[list["GroupNode"], list["GroupEdge"]]:
    """加载群组的拓扑（已在内存中）"""
    nodes = list(group.nodes.all())
    edges = list(group.edges.all())
    return nodes, edges


class GroupExecutor:
    """群组拓扑执行器"""

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    async def run(
        self, session: "ChatSession", user_message: str, group: "AgentGroup"
    ) -> list[AgentMessage]:
        """非流式执行"""
        messages: list[AgentMessage] = []
        async for event in self.run_stream(session, user_message, group):
            if event.get("type") == "assistant":
                messages.append(AgentMessage(
                    role="assistant",
                    content=event["content"],
                    name=event.get("agent_name", ""),
                    metadata=event.get("metadata", {}),
                ))
        return messages

    async def run_stream(
        self, session: "ChatSession", user_message: str, group: "AgentGroup"
    ) -> AsyncGenerator[dict, None]:
        """流式执行拓扑"""
        nodes, edges = await load_topology(group)
        if not nodes:
            yield {"type": "error", "content": "该群组尚未配置拓扑节点"}
            return

        # 找到 Start 节点
        start_node = next((n for n in nodes if n.node_type == "start"), None)
        if not start_node:
            yield {"type": "error", "content": "缺少 Start 节点"}
            return

        yield {"type": "status", "agent_name": "群组执行器", "content": f"🔗 开始执行群组「{group.name}」（{len(nodes)}个节点）"}

        # 单条线执行：Start → next → next → ... → End
        current = start_node
        visited = set()
        results: dict[str, str] = {}  # node_label → output

        while current:
            node_key = str(current.pk)
            if node_key in visited:
                yield {"type": "error", "content": f"检测到循环引用: {current.label}"}
                break
            visited.add(node_key)

            if current.node_type == "start":
                yield {"type": "status", "agent_name": "群组执行器", "content": f"⏳ 开始 → {current.label}"}

            elif current.node_type == "agent" and current.agent and current.agent.llm_config:
                yield {"type": "status", "agent_name": current.label, "content": f"正在调用 {current.label}..."}

                tools = await get_tools_for_agent_async(current.agent, self.tool_registry)
                from . import prompts as _prompts

                system_prompt = (
                    current.agent.system_prompt or f"你是{current.agent.name}，请分析以下问题。"
                )
                system_prompt += "\n\n" + _prompts.EXPERT_INDEPENDENT_PROMPT.format(
                    agent_name=current.agent.name,
                    role="群组成员",
                    expertise=current.agent.description or "通用分析",
                    user_question=user_message,
                    skills_meta="",
                    tools_desc="请使用可用工具获取数据后再分析",
                )
                # 将上下游结果注入上下文
                upstream = self._collect_upstream(current, edges, nodes, results)
                if upstream:
                    system_prompt += f"\n\n## 上游输出\n{upstream}"

                executor = get_executor(current.agent, tool_registry=self.tool_registry)
                try:
                    result = await executor.execute(
                        agent=current.agent,
                        user_message=user_message,
                        context_messages=[],
                        tools=tools if tools else None,
                        system_prompt_override=system_prompt,
                    )
                except Exception as e:
                    logger.exception("Node %s failed", current.label)
                    yield {"type": "error", "agent_name": current.label, "content": f"执行错误: {e}"}
                    results[current.label] = f"[错误] {e}"
                    current = self._next_node(current, edges, nodes)
                    continue

                # Yield 思考和状态
                for trace in result.thinking_trace:
                    yield {
                        "type": "thinking", "agent_name": current.label,
                        "stage": trace.get("stage", ""),
                        "content": trace.get("content", "")[:500],
                    }
                for tc in result.tool_calls:
                    yield {
                        "type": "tool_call", "agent_name": current.label,
                        "tool": tc.get("tool", ""), "args": tc.get("args", ""),
                    }
                for sm in result.status_messages:
                    yield {"type": "status", "agent_name": current.label, "content": sm}

                # 最终回复
                yield {
                    "type": "assistant", "content": result.content,
                    "agent_name": current.label, "role": "expert",
                    "metadata": {
                        "thinking": result.thinking_trace,
                        "stage": result.stage,
                        "agent_type": getattr(current.agent, "agent_type", "react"),
                        "topology_node": current.label,
                    },
                }
                results[current.label] = result.content

            elif current.node_type == "condition":
                # 评估条件 → 选择分支边
                last_result = results.get(list(results.keys())[-1] if results else "", "")
                condition_edge = None
                for e in edges:
                    if e.source_id == current.pk:
                        if not e.condition:
                            condition_edge = e  # 无条件 → 默认
                        elif e.condition.lower() in last_result.lower():
                            condition_edge = e
                            yield {"type": "status", "agent_name": current.label, "content": f"✅ 条件匹配: {e.condition}"}
                        else:
                            yield {"type": "status", "agent_name": current.label, "content": f"❌ 条件不匹配: {e.condition}"}
                current = self._follow_edge(condition_edge, nodes) if condition_edge else None
                if condition_edge:
                    yield {"type": "status", "agent_name": current.label if current else "群组执行器",
                           "content": f"🔀 条件分支 → {current.label if current else 'End'}"}
                continue

            elif current.node_type == "end":
                yield {"type": "status", "agent_name": "群组执行器", "content": "✅ 执行完成"}
                break

            # 找下一个节点
            current = self._next_node(current, edges, nodes)

        yield {"type": "done"}

    def _next_node(self, node: "GroupNode", edges: list["GroupEdge"], nodes: list["GroupNode"]) -> "GroupNode | None":
        """获取当前节点的下一个节点"""
        for e in edges:
            if e.source_id == node.pk:
                return next((n for n in nodes if n.pk == e.target_id), None)
        return None

    def _follow_edge(self, edge: "GroupEdge | None", nodes: list["GroupNode"]) -> "GroupNode | None":
        """沿边获取目标节点"""
        if not edge:
            return None
        return next((n for n in nodes if n.pk == edge.target_id), None)

    def _collect_upstream(self, node: "GroupNode", edges: list["GroupEdge"],
                           nodes: list["GroupNode"], results: dict[str, str]) -> str:
        """收集上游节点的输出"""
        upstream = []
        for e in edges:
            if e.target_id == node.pk:
                src = next((n for n in nodes if n.pk == e.source_id), None)
                if src and src.label in results:
                    upstream.append(f"### {src.label}\n{results[src.label][:500]}")
        return "\n\n".join(upstream)
