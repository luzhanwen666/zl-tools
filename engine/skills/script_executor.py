"""
智能体引擎 - Skills 脚本执行器

Level 3 资源执行：运行 skills_storage/ 目录下的 Python 脚本。
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

SCRIPT_TIMEOUT = 30  # 脚本执行超时秒数


class SkillScriptExecutor:
    """Skills 脚本执行器 — 运行技能附带的 Python 脚本"""

    @staticmethod
    async def execute_script(
        skill_name: str,
        script_name: str,
        args: list[str] | None = None,
        cwd: str | None = None,
    ) -> str:
        """
        执行技能附带的 Python 脚本。

        Args:
            skill_name: 技能名称（对应 skills_storage/{skill_name}/ 目录）
            script_name: 脚本文件名（如 "parse_pdf.py"）
            args: 命令行参数列表
            cwd: 工作目录（默认为脚本所在目录）

        Returns:
            str: stdout + stderr 输出
        """
        script_path = os.path.join("skills_storage", skill_name, "scripts", script_name)
        if not os.path.exists(script_path):
            return f"[错误] 脚本不存在: {script_path}"

        work_dir = cwd or os.path.dirname(script_path)

        cmd = ["python", script_path] + (args or [])
        logger.info("SkillScript: executing %s", cmd)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=SCRIPT_TIMEOUT,
            )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.warning("SkillScript exited with code %d: %s", proc.returncode, stderr_text[:200])
                return f"[脚本错误 (exit={proc.returncode})]\n{stderr_text}\n{stdout_text}"

            return stdout_text or stderr_text

        except asyncio.TimeoutError:
            return f"[错误] 脚本执行超时（{SCRIPT_TIMEOUT}秒）: {script_path}"
        except Exception as e:
            logger.exception("SkillScript execution failed")
            return f"[错误] 脚本执行失败: {e}"

    @staticmethod
    async def execute_code(code: str, timeout: int = 10) -> str:
        """
        执行任意 Python 代码片段（沙箱不完整，仅用于受信任的技能环境）。

        Args:
            code: Python 代码字符串
            timeout: 超时秒数

        Returns:
            str: stdout 输出
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                return f"[代码错误]\n{stderr_text}"

            return stdout_text or stderr_text

        except asyncio.TimeoutError:
            return f"[错误] 代码执行超时（{timeout}秒）"
        except Exception as e:
            return f"[错误] 代码执行失败: {e}"
