"""
智能体引擎 - 工具注册与管理

负责从 Agent 配置中收集工具：
- SkillScriptTool — 读取 SKILL.md 提取真实命令示例作为工具描述
- MCP 工具
- 内置工具（builtin/）
"""

import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING

from .base import BaseTool, ToolRegistry

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SkillScriptTool
# ═══════════════════════════════════════════════════════════════════

class SkillScriptTool(BaseTool):
    """
    将技能脚本包装为可执行工具。

    工具描述和参数示例从 SKILL.md 中提取，让 LLM 看到
    与 SKILL.md 完全一致的命令格式。
    """

    def __init__(self, skill_name: str, script_path: str, script_name: str,
                 description: str = "", usage_examples: str = ""):
        self.skill_name = skill_name
        self.script_path = script_path
        self.script_name = script_name
        self.name = f"skill_{skill_name}_{script_name.replace('.py', '').replace('.', '_')}"
        self.description = description
        self.usage_examples = usage_examples  # SKILL.md 中的命令示例
        self.parameters = {
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": "命令行参数，按 SKILL.md 中的格式传入。例如：run_skill.py 需要 --target <url> --output-json <path>",
                },
                "stdin_text": {
                    "type": "string",
                    "description": "通过 stdin 传给脚本的文本（如 'y' 用于确认）。默认 'y\\n'",
                },
                "env_vars": {
                    "type": "object",
                    "description": "环境变量字典。如 SKILL.md 提到需要 BASE_URL/API_TOKEN，从这里传入",
                },
            },
            "required": [],
        }

    async def execute(self, args: str = "", stdin_text: str = "y\n",
                       env_vars: dict | None = None, **kwargs) -> str:
        if not os.path.exists(self.script_path):
            return f"[技能错误] 脚本不存在: {self.script_path}"

        cmd = ["python", self.script_path] + (args.split() if args else [])
        work_dir = os.path.dirname(self.script_path)

        child_env = os.environ.copy()
        if env_vars:
            child_env.update(env_vars)

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
                proc.communicate(input=stdin_bytes), timeout=120,
            )
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                logger.warning("SkillScript %s exit=%d: %s", self.script_name, proc.returncode, err[:300])
                return f"[退出码 {proc.returncode}]\n{out}\n{err}"
            return out or err
        except asyncio.TimeoutError:
            return f"[超时] {self.script_name} 超过120秒"
        except Exception as e:
            logger.exception("SkillScript failed")
            return f"[错误] {e}"


# ═══════════════════════════════════════════════════════════════════
# 从 SKILL.md 提取命令示例
# ═══════════════════════════════════════════════════════════════════

def _extract_command_examples(skill_md_path: str, script_name: str) -> str:
    """
    从 SKILL.md 中提取与 script_name 相关的命令示例，
    用作工具描述的一部分，让 LLM 知道如何调用。
    """
    if not os.path.exists(skill_md_path):
        return ""

    try:
        content = open(skill_md_path, encoding="utf-8").read()
    except Exception:
        return ""

    examples = []
    in_code_block = False
    current_block = []

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                # 结束代码块
                block_text = "\n".join(current_block)
                if script_name in block_text and ("python" in block_text.lower()):
                    # 只保留命令本身，去掉 cd 和 &&
                    cmds = [l.strip() for l in current_block
                            if l.strip() and not l.strip().startswith("#")
                            and script_name in l]
                    if cmds:
                        examples.extend(cmds)
                current_block = []
                in_code_block = False
            else:
                in_code_block = True
                current_block = []
        elif in_code_block:
            current_block.append(line)

    if not examples:
        return ""

    # 精简示例列表
    unique = list(dict.fromkeys(examples))  # 去重保序
    return "\n".join(f"  示例: {cmd}" for cmd in unique[:3])


def _get_skill_script_tools(agent: "AgentModel") -> list[SkillScriptTool]:
    """
    扫描 Agent 绑定的技能，为每个 .py 脚本创建工具。
    工具描述融合 SKILL.md 中的命令示例。
    """
    tools: list[SkillScriptTool] = []
    skills = [s for s in agent.skills.all() if s.is_active and s.script_dir]

    for skill in skills:
        scripts_dir = os.path.join(skill.script_dir, "scripts")
        if not os.path.isdir(scripts_dir):
            continue

        skill_md_path = os.path.join(skill.script_dir, "SKILL.md")

        for fname in sorted(os.listdir(scripts_dir)):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(scripts_dir, fname)
            if not os.path.isfile(fpath):
                continue

            # 提取命令行示例
            cmd_examples = _extract_command_examples(skill_md_path, fname)

            # 构建描述
            if cmd_examples:
                desc = (
                    f"执行「{skill.name}」的 {fname}。"
                    f"\n{cmd_examples}"
                )
            else:
                desc = f"执行「{skill.name}」的 {fname}"

            tools.append(SkillScriptTool(
                skill_name=skill.name,
                script_path=fpath,
                script_name=fname,
                description=desc,
                usage_examples=cmd_examples,
            ))

    return tools


# ═══════════════════════════════════════════════════════════════════
# MCP + 内置工具（保持）
# ═══════════════════════════════════════════════════════════════════

class MCPToolWrapper(BaseTool):
    """MCP 工具包装器"""

    def __init__(self, mcp_config):
        self.name = f"mcp_{mcp_config.name.lower().replace(' ', '_')}"
        self.description = mcp_config.description or f"MCP: {mcp_config.name}"
        self.mcp_config = mcp_config
        self._remote_tools: list[dict] = []
        self._connected = False
        self.parameters = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "操作"},
                "params": {"type": "object", "description": "参数"},
            },
            "required": ["action"],
        }

    async def _ensure_connected(self) -> list[dict]:
        if not self._connected:
            try:
                from .mcp_pool import MCPConnectionPool
                client = await MCPConnectionPool.get_instance().get_client(self.mcp_config)
                self._remote_tools = MCPConnectionPool.get_instance().get_cached_tools(self.mcp_config)
                self._connected = True
            except Exception as e:
                logger.error("MCP connect failed '%s': %s", self.mcp_config.name, e)
                self._connected = True
        return self._remote_tools

    async def execute(self, action: str = "", params: dict | None = None, **kwargs) -> str:
        remote = await self._ensure_connected()
        if not remote:
            return f"[MCP: {self.mcp_config.name}] 未连接"
        try:
            from .mcp_pool import MCPConnectionPool
            client = await MCPConnectionPool.get_instance().get_client(self.mcp_config)
            tool_name = next((t["name"] for t in remote if t.get("name") == action), remote[0]["name"])
            return await client.call_tool(tool_name, params or {})
        except Exception as e:
            return f"[MCP错误] {e}"


def get_tools_for_agent(agent: "AgentModel", builtin_registry: ToolRegistry | None = None) -> list[BaseTool]:
    """收集 Agent 的可用工具"""
    tools: list[BaseTool] = []

    skill_tools = _get_skill_script_tools(agent)
    tools.extend(skill_tools)
    if skill_tools:
        logger.info("Agent %s: %d skill tools", agent.name, len(skill_tools))

    for mcp in agent.mcp_tools.filter(is_active=True):
        tools.append(MCPToolWrapper(mcp))

    if builtin_registry:
        tools.extend(builtin_registry.get_all())

    return tools


from asgiref.sync import sync_to_async
get_tools_for_agent_async = sync_to_async(get_tools_for_agent)
