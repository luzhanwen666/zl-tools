"""
智能体引擎 - 工具注册与管理

负责从 Agent 配置中收集工具：
- 内置工具（builtin/）
- 技能脚本工具（Skill → SkillScriptTool）→ 真实执行 skills_storage 下的脚本
- MCP 工具（MCPToolConfig → MCPToolWrapper）
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from .base import BaseTool, ToolRegistry

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel

logger = logging.getLogger(__name__)


class SkillScriptTool(BaseTool):
    """
    将技能脚本包装为可执行工具。

    当 Agent 绑定了有 script_dir 的技能时，扫描 scripts/ 目录，
    每个 .py 文件暴露为一个可调用工具。
    """

    def __init__(self, skill_name: str, script_path: str, script_name: str,
                 description: str = ""):
        self.skill_name = skill_name
        self.script_path = script_path        # 绝对路径
        self.script_name = script_name        # 文件名，如 main.py
        self.name = f"skill_{skill_name}_{script_name.replace('.py', '').replace('.', '_')}"
        self.description = description or f"执行技能「{skill_name}」的脚本 {script_name}"
        self.parameters = {
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": "传给脚本的命令行参数，多个参数用空格分隔",
                },
                "stdin_text": {
                    "type": "string",
                    "description": "通过 stdin 传给脚本的文本（如 'y' 用于确认提示）。默认自动传 'y'。",
                },
                "env_vars": {
                    "type": "object",
                    "description": "传给脚本的环境变量。如果脚本需要 BASE_URL 和 API_TOKEN，从这里传入。例如: {\"BASE_URL\":\"https://192.168.0.215:9443\",\"API_TOKEN\":\"xxx\"}",
                },
            },
            "required": [],
        }

    async def execute(self, args: str = "", stdin_text: str = "y\n",
                       env_vars: dict | None = None, **kwargs) -> str:
        """执行技能脚本"""
        if not os.path.exists(self.script_path):
            return f"[技能错误] 脚本不存在: {self.script_path}"

        cmd = ["python", self.script_path] + (args.split() if args else [])
        work_dir = os.path.dirname(self.script_path)

        # 构建环境变量（继承当前进程环境 + 用户传入的）
        child_env = os.environ.copy()
        if env_vars:
            child_env.update(env_vars)
            logger.info("SkillScript env: %s", {k: v[:8]+"***" if k == "API_TOKEN" else v for k, v in env_vars.items()})

        logger.info("SkillScript: %s (cwd=%s)", " ".join(cmd), work_dir)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=child_env,
            )

            stdin_bytes = (stdin_text or "y\n").encode("utf-8")
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=60,
            )

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.warning("SkillScript %s exited %d: %s", self.script_name, proc.returncode, err[:300])
                return f"[脚本退出码 {proc.returncode}]\n{out}\n{err}"

            return out or err

        except asyncio.TimeoutError:
            return f"[技能错误] 脚本执行超时（60秒）: {self.script_name}"
        except Exception as e:
            logger.exception("SkillScript execution failed")
            return f"[技能错误] {self.script_name}: {e}"


def _get_skill_script_tools(agent: "AgentModel") -> list[SkillScriptTool]:
    """
    扫描 Agent 绑定技能中所有带脚本目录的技能，
    为每个 .py 脚本创建一个可执行工具。
    """
    tools: list[SkillScriptTool] = []
    skills = [s for s in agent.skills.all() if s.is_active and s.script_dir]

    for skill in skills:
        scripts_dir = os.path.join(skill.script_dir, "scripts")
        if not os.path.isdir(scripts_dir):
            continue

        for fname in sorted(os.listdir(scripts_dir)):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(scripts_dir, fname)
            if not os.path.isfile(fpath):
                continue

            # 读取文件前几行，提取简要描述
            desc = f"执行技能「{skill.name}」的 {fname}"
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    first_lines = "".join(fh.readline() for _ in range(5))
                if "argparse" in first_lines or "ArgumentParser" in first_lines:
                    desc = f"技能「{skill.name}」主脚本 {fname} — 接受命令行参数"
                elif "def " in first_lines:
                    funcs = [l.strip() for l in first_lines.split("\n") if l.strip().startswith("def ")]
                    if funcs:
                        desc = f"技能「{skill.name}」脚本 {fname} — 提供: {', '.join(f[:40] for f in funcs[:3])}"
            except Exception:
                pass

            tools.append(SkillScriptTool(
                skill_name=skill.name,
                script_path=fpath,
                script_name=fname,
                description=desc,
            ))

    return tools


class MCPToolWrapper(BaseTool):
    """将 MCPToolConfig 包装为工具 — 真实 MCP 协议调用"""

    def __init__(self, mcp_config):
        self.name = f"mcp_{mcp_config.name.lower().replace(' ', '_')}"
        self.description = mcp_config.description or f"MCP工具: {mcp_config.name}"
        self.mcp_config = mcp_config
        self._remote_tools: list[dict] = []
        self._connected = False
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "要执行的操作"},
                "params": {"type": "object", "description": "操作参数"},
            },
            "required": ["action"],
        }

    async def _ensure_connected(self) -> list[dict]:
        if not self._connected:
            try:
                from .mcp_pool import MCPConnectionPool
                pool = MCPConnectionPool.get_instance()
                client = await pool.get_client(self.mcp_config)
                self._remote_tools = pool.get_cached_tools(self.mcp_config)
                self._connected = True
                logger.info("MCP connected: %s → %d tools", self.mcp_config.name, len(self._remote_tools))
            except Exception as e:
                logger.error("MCP connect failed '%s': %s", self.mcp_config.name, e)
                self._remote_tools = []
                self._connected = True
        return self._remote_tools

    async def execute(self, action: str = "", params: dict | None = None, **kwargs) -> str:
        remote_tools = await self._ensure_connected()
        if not remote_tools:
            return f"[MCP: {self.mcp_config.name}] 未连接到远程 MCP 服务。"
        try:
            from .mcp_pool import MCPConnectionPool
            pool = MCPConnectionPool.get_instance()
            client = await pool.get_client(self.mcp_config)
            if action:
                matching = [t for t in remote_tools if t.get("name") == action]
                tool_name = action if matching else remote_tools[0].get("name", action)
                if not matching:
                    params = {"query": action, **(params or {})}
            else:
                tool_name = remote_tools[0].get("name", "unknown")
                params = params or {}
            return await client.call_tool(tool_name, params)
        except Exception as e:
            logger.exception("MCP execution failed")
            return f"[MCP错误: {self.mcp_config.name}] {e}"

    def get_remote_tool_definitions(self) -> list[dict]:
        return self._remote_tools


def get_tools_for_agent(agent: "AgentModel", builtin_registry: ToolRegistry | None = None) -> list[BaseTool]:
    """
    收集 Agent 的可用工具：
    - 技能脚本工具（skills_storage 下的 .py 脚本）
    - MCP 工具
    - 内置工具（shell, python, web_search 等）
    """
    tools: list[BaseTool] = []

    # ── 技能脚本工具 ──
    skill_tools = _get_skill_script_tools(agent)
    tools.extend(skill_tools)
    if skill_tools:
        logger.info("Agent %s has %d skill script tools", agent.name, len(skill_tools))

    # ── MCP 工具 ──
    for mcp in agent.mcp_tools.filter(is_active=True):
        tools.append(MCPToolWrapper(mcp))

    # ── 内置工具 ──
    if builtin_registry:
        tools.extend(builtin_registry.get_all())

    return tools


# sync_to_async 包装版本
from asgiref.sync import sync_to_async
get_tools_for_agent_async = sync_to_async(get_tools_for_agent)
