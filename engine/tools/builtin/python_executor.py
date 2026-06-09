"""
智能体引擎 - 内置工具：Python 脚本执行器

Agent 可直接传入 Python 代码并执行，无需修改 SKILL.md 文件。
适用于技能指令中内置的 Python 脚本。
"""

import asyncio
import os
import tempfile

from engine.tools.base import BaseTool


class PythonExecutorTool(BaseTool):
    """Python 脚本执行工具"""

    name = "python"
    description = (
        "执行 Python 脚本。传入 Python 代码字符串，返回标准输出和错误。"
        "超时30秒，输出上限10000字符。"
        "适用场景：技能指令中的 Python 脚本、数据处理、API 调用等。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码",
            },
        },
        "required": ["code"],
    }

    async def execute(self, code: str, **kwargs) -> str:
        timeout = 30
        max_output = 10000

        # 写入临时文件执行（避免命令行转义问题）
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        try:
            tmp.write(code)
            tmp.close()

            proc = await asyncio.create_subprocess_exec(
                "python", tmp.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            return f"[超时] 脚本执行超过 {timeout} 秒，已终止"
        except Exception as e:
            return f"[错误] 执行失败: {str(e)}"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
