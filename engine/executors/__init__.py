"""
智能体引擎 - 执行器包

提供 4 种 Agent 执行策略：
- ReactExecutor: 思考-行动-观察循环
- SimpleExecutor: 直接问答
- ReflectionExecutor: 生成-反思-改进
- PlanAndSolveExecutor: 先规划后执行
"""

from .base_executor import BaseAgentExecutor, AgentExecutionResult
from .react_executor import ReactExecutor
from .simple_executor import SimpleExecutor
from .reflection_executor import ReflectionExecutor
from .plan_and_solve_executor import PlanAndSolveExecutor
from .dispatcher import get_executor, run_agent

__all__ = [
    "BaseAgentExecutor",
    "AgentExecutionResult",
    "ReactExecutor",
    "SimpleExecutor",
    "ReflectionExecutor",
    "PlanAndSolveExecutor",
    "get_executor",
    "run_agent",
]
