"""
智能体引擎 - 内置工具：日志解析器
"""

import json
import re
from engine.tools.base import BaseTool


class LogParserTool(BaseTool):
    """安全日志解析工具"""

    name = "log_parser"
    description = "解析安全日志，提取关键字段（时间、IP、用户、操作类型、状态等），支持常见日志格式"
    parameters = {
        "type": "object",
        "properties": {
            "raw_logs": {
                "type": "string",
                "description": "原始日志文本",
            },
            "log_type": {
                "type": "string",
                "description": "日志类型：syslog / apache / nginx / windows_event / generic",
                "enum": ["syslog", "apache", "nginx", "windows_event", "generic"],
                "default": "generic",
            },
        },
        "required": ["raw_logs"],
    }

    async def execute(self, raw_logs: str, log_type: str = "generic", **kwargs) -> str:
        lines = raw_logs.strip().split("\n")
        parsed = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            entry = self._parse_line(line, log_type)
            if entry:
                parsed.append(entry)

        result = {
            "total_lines": len(lines),
            "parsed_entries": len(parsed),
            "entries": parsed[:100],  # 最多返回 100 条
        }
        if len(parsed) > 100:
            result["truncated"] = True
            result["truncated_count"] = len(parsed) - 100

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _parse_line(self, line: str, log_type: str) -> dict | None:
        """解析单行日志"""
        entry: dict = {"raw": line}

        if log_type == "syslog":
            m = re.match(r"(\w{3}\s+\d+\s+[\d:]+)\s+(\S+)\s+(\S+?)(?:\[(\d+)\])?:\s+(.*)", line)
            if m:
                entry["timestamp"] = m.group(1)
                entry["host"] = m.group(2)
                entry["app"] = m.group(3)
                entry["message"] = m.group(5)
                entry["log_type"] = "syslog"
                return entry

        elif log_type in ("apache", "nginx"):
            m = re.match(r'(\S+)\s+(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+"(\S+)\s+(\S+)\s+\S+\s+"([^"]*)"\s+(\d+)\s+(\d+)', line)
            if m:
                entry["ip"] = m.group(1)
                entry["timestamp"] = m.group(4)
                entry["method"] = m.group(5)
                entry["path"] = m.group(6)
                entry["status"] = int(m.group(8))
                entry["size"] = int(m.group(9))
                entry["log_type"] = log_type
                return entry

        elif log_type == "windows_event":
            m = re.search(r"EventID:\s*(\d+)", line, re.IGNORECASE)
            if m:
                entry["event_id"] = m.group(1)
            m = re.search(r"Source:\s*(\S+)", line, re.IGNORECASE)
            if m:
                entry["source"] = m.group(1)
            entry["log_type"] = "windows_event"
            return entry if entry.get("event_id") else None

        else:  # generic
            # 尝试提取 IP
            ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", line)
            if ip_match:
                entry["ip"] = ip_match.group(1)
            # 尝试提取时间
            time_match = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2})", line)
            if time_match:
                entry["timestamp"] = time_match.group(1)
            # 尝试提取用户
            user_match = re.search(r"user[=:\s]+(\S+)", line, re.IGNORECASE)
            if user_match:
                entry["user"] = user_match.group(1)
            entry["log_type"] = "generic"
            return entry

        return None
