"""
智能体引擎 - 内置工具：Shell 命令执行

支持 Windows (PowerShell/cmd)、Linux (bash)、Mac (bash/zsh)。
Agent 可通过此工具直接执行系统命令。
"""

import asyncio
import os
import platform

from engine.tools.base import BaseTool


class ShellTool(BaseTool):
    """跨平台 Shell 命令执行工具"""

    name = "shell"
    description = (
        "执行系统命令。支持 Windows(PowerShell/cmd)、Linux(bash)、Mac(bash/zsh)。"
        "可用于运行脚本、调用 API(curl)、文件操作等。"
        "超时30秒，输出上限10000字符。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令",
            },
            "cwd": {
                "type": "string",
                "description": "工作目录（可选，默认当前目录）",
            },
        },
        "required": ["command"],
    }

    async def execute(self, command: str, cwd: str | None = None, **kwargs) -> str:
        timeout = 30
        max_output = 10000

        # 自动选择 shell
        system = platform.system()
        if system == "Windows":
            shell_cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            shell_cmd = ["bash", "-c", command]

        work_dir = cwd or os.getcwd()

        try:
            proc = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            result_parts = []
            if out.strip():
                result_parts.append(out[:max_output])
                if len(out) > max_output:
                    result_parts.append(f"\n...(输出截断，共 {len(out)} 字符)")
            if err.strip():
                result_parts.append(f"\n[stderr]\n{err[:max_output]}")

            result_parts.append(f"\n[退出码: {proc.returncode}]")
            return "".join(result_parts)

        except asyncio.TimeoutError:
            proc.kill()
            return f"[超时] 命令执行超过 {timeout} 秒，已终止"
        except FileNotFoundError:
            return f"[错误] 找不到 shell 程序: {shell_cmd[0]}"
        except Exception as e:
            return f"[错误] 命令执行失败: {str(e)}"
