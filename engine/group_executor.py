"""
群组拓扑执行器 — 按连线顺序遍历执行

从 Start 节点出发，沿 GroupEdge 连线严格顺序执行：
- 单线串行：Start → A → B → C → End
- 多线并行：Start → ┬→ A →┬→ Merge → End
                      └→ B →┘
- 条件分支：Condition → success边→A, failure边→B
- 每个 agent 节点注入上游输出作为上下文
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import AsyncGenerator, TYPE_CHECKING

from .schemas import AgentMessage
from .executors import get_executor
from .tools.base import ToolRegistry
from .tools.registry import get_tools_for_agent_async

if TYPE_CHECKING:
    from agents.models import Agent, AgentGroup, GroupNode, GroupEdge
    from chat.models import ChatSession

logger = logging.getLogger(__name__)


class GroupExecutor:
    """群组拓扑执行器 — 严格按连线顺序"""

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    async def run(
        self, session: "ChatSession", user_message: str, group: "AgentGroup"
    ) -> list[AgentMessage]:
        messages: list[AgentMessage] = []
        async for event in self.run_stream(session, user_message, group):
            if event.get("type") == "assistant":
                messages.append(AgentMessage(
                    role="assistant", content=event["content"],
                    name=event.get("agent_name", ""),
                    metadata=event.get("metadata", {}),
                ))
        return messages

    async def run_stream(
        self, session: "ChatSession", user_message: str, group: "AgentGroup",
        preloaded_nodes: list | None = None, preloaded_edges: list | None = None,
    ) -> AsyncGenerator[dict, None]:
        # 使用预加载数据（在同步上下文中已 select_related），避免 async 懒查询
        if preloaded_nodes is not None:
            nodes = preloaded_nodes
            edges = preloaded_edges or list(group.edges.all())
        else:
            nodes = list(group.nodes.all())
            edges = list(group.edges.all())

        if not nodes:
            yield {"type": "error", "content": "该群组尚未配置拓扑节点"}
            return

        # 构建邻接表：source_id → [(edge, target_node)]
        outgoing: dict[int, list] = {}
        node_map: dict[int, "GroupNode"] = {n.pk: n for n in nodes}
        for e in edges:
            outgoing.setdefault(e.source_id, []).append((e, node_map.get(e.target_id)))

        start = next((n for n in nodes if n.node_type == "start"), None)
        if not start:
            yield {"type": "error", "content": "缺少 Start 节点"}
            return

        yield {"type": "status", "agent_name": "群组执行器",
               "content": f"🔗 执行群组「{group.name}」({len(nodes)}节点, {len(edges)}连线)"}

        results: dict[str, str] = {}  # node_label → output
        visited: set[int] = set()

        # BFS 按连线顺序遍历
        queue: deque = deque()
        queue.append(start)

        while queue:
            current = queue.popleft()

            if current.pk in visited:
                continue
            visited.add(current.pk)

            if current.node_type == "end":
                yield {"type": "status", "agent_name": "群组执行器", "content": "✅ 拓扑执行完成"}
                continue

            if current.node_type == "start":
                yield {"type": "status", "agent_name": "群组执行器",
                       "content": "▶ 开始执行拓扑"}
                for _, target in outgoing.get(current.pk, []):
                    if target and target.pk not in visited:
                        queue.append(target)
                continue

            if current.node_type == "agent" and current.agent and current.agent.llm_config:
                # ── 执行 Agent 节点 ──
                yield {"type": "status", "agent_name": current.label,
                       "content": f"正在调用 {current.label}..."}

                tools = await get_tools_for_agent_async(current.agent, self.tool_registry)
                from . import prompts as _prompts

                system_prompt = (current.agent.system_prompt
                                 or f"你是{current.agent.name}，请分析以下问题。")
                system_prompt += "\n\n" + _prompts.EXPERT_INDEPENDENT_PROMPT.format(
                    agent_name=current.agent.name, role="群组成员",
                    expertise=current.agent.description or "通用分析",
                    user_question=user_message,
                    skills_meta="",
                    tools_desc="请使用可用工具获取数据后再分析",
                )

                # 注入上游节点输出
                upstream = self._collect_upstream(current, edges, node_map, results)
                if upstream:
                    system_prompt += f"\n\n## 上游输出（请基于此继续分析）\n{upstream}"

                executor = get_executor(current.agent, tool_registry=self.tool_registry)
                try:
                    result = await executor.execute(
                        agent=current.agent, user_message=user_message,
                        context_messages=[], tools=tools if tools else None,
                        system_prompt_override=system_prompt,
                    )
                except Exception as e:
                    logger.exception("Node %s failed", current.label)
                    yield {"type": "error", "agent_name": current.label,
                           "content": f"执行错误: {e}"}
                    results[current.label] = f"[错误] {e}"
                    # 即使失败也继续下游
                    for _, target in outgoing.get(current.pk, []):
                        if target and target.pk not in visited:
                            queue.append(target)
                    continue

                # 全部 thinking trace 直接 yield，不做过滤
                for trace in result.thinking_trace:
                    yield {"type": "thinking", "agent_name": current.label,
                           "stage": trace.get("stage", ""),
                           "content": trace.get("content", "")[:500]}
                for tc in result.tool_calls:
                    yield {"type": "tool_call", "agent_name": current.label,
                           "tool": tc.get("tool", ""), "args": tc.get("args", "")}
                for sm in result.status_messages:
                    yield {"type": "status", "agent_name": current.label,
                           "content": sm}
                yield {
                    "type": "assistant", "content": result.content,
                    "agent_name": current.label, "role": "expert",
                    "metadata": {
                        "thinking": result.thinking_trace, "stage": result.stage,
                        "tool_calls": result.tool_calls,
                        "agent_type": getattr(current.agent, "agent_type", "react"),
                        "topology_node": current.label,
                    },
                }
                results[current.label] = result.content

            elif current.node_type == "condition":
                # 评估条件 → 选分支边
                last_output = ""
                for key in reversed(list(results.keys())):
                    last_output = results[key]
                    break
                matched = False
                for edge, target in outgoing.get(current.pk, []):
                    if target and target.pk not in visited:
                        if not edge.condition or edge.condition.lower() in last_output.lower():
                            yield {"type": "status", "agent_name": current.label,
                                   "content": f"🔀 条件 '{edge.condition or '默认'}' → {target.label}"}
                            queue.append(target)
                            matched = True
                            break
                if not matched:
                    # 无条件边 → 走第一条
                    for edge, target in outgoing.get(current.pk, []):
                        if target and target.pk not in visited:
                            queue.append(target)
                            break

            elif current.node_type == "parallel":
                # 所有下游并行加入队列
                downstream = []
                for _, target in outgoing.get(current.pk, []):
                    if target and target.pk not in visited:
                        downstream.append(target)
                        queue.append(target)
                yield {"type": "status", "agent_name": current.label,
                       "content": f"⫼ 并行分发 → {len(downstream)} 路"}

            elif current.node_type == "merge":
                yield {"type": "status", "agent_name": current.label,
                       "content": "⫻ 等待合并..."}
                for _, target in outgoing.get(current.pk, []):
                    if target and target.pk not in visited:
                        queue.append(target)

            else:
                # 其他类型直接传递给下游
                for _, target in outgoing.get(current.pk, []):
                    if target and target.pk not in visited:
                        queue.append(target)

        yield {"type": "done"}

    def _collect_upstream(self, node: "GroupNode", edges: list["GroupEdge"],
                           node_map: dict[int, "GroupNode"],
                           results: dict[str, str]) -> str:
        upstream = []
        for e in edges:
            if e.target_id == node.pk:
                src = node_map.get(e.source_id)
                if src and src.label in results:
                    upstream.append(
                        f"### {src.label}\n{results[src.label][:800]}"
                    )
        return "\n\n".join(upstream)
