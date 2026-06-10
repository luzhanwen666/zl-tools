"""
Skills 渐进式加载器 — 纯 LLM 驱动，不做关键词匹配

Layer 1: system prompt 注入技能名 + 描述（始终加载）
Layer 2: LLM 回复 [USE_SKILL:name] → 加载 SKILL.md 完整内容
Layer 3: 脚本已注册为工具，LLM 按 SKILL.md 中的命令格式调用

核心理念（Extra05-AgentSkills解读.md）：
  Skills = "操作手册"（告诉 LLM 如何做事）
  每个 SKILL.md 都有「触发时机」章节 → LLM 读后自行判断是否需要
  不做关键词猜测，让 LLM 自己做决策
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel

logger = logging.getLogger(__name__)


def _active_skills(agent: "AgentModel") -> list:
    return [s for s in agent.skills.all() if s.is_active]


class SkillsLoader:
    """纯 LLM 驱动的技能加载器"""

    @staticmethod
    def load_layer1_metadata(agent: "AgentModel") -> str:
        """
        Layer 1: 技能名 + 触发时机（提取自 SKILL.md）。
        始终注入 system prompt，让 LLM 自行判断。
        """
        skills = _active_skills(agent)
        if not skills:
            return ""

        lines = ["## 可用技能"]
        for s in skills:
            desc = (s.description or "通用技能")[:120]
            # 提取 SKILL.md 中「触发时机」章节内容
            trigger = ""
            skill_md = os.path.join(s.script_dir, "SKILL.md") if s.script_dir else ""
            if skill_md and os.path.exists(skill_md):
                try:
                    content = open(skill_md, encoding="utf-8").read()
                    m = re.search(
                        r'##\s*触发时机\s*\n+(.*?)(?=\n##\s|\Z)',
                        content, re.DOTALL
                    )
                    if m:
                        trigger = m.group(1).strip()[:300]
                except Exception:
                    pass

            trigger_text = f"\n  > 触发: {trigger}" if trigger else ""
            lines.append(f"- **{s.name}**：{desc}{trigger_text}")

        lines.append(
            "\n💡 以上技能已载入元数据。"
            "当任务匹配某技能的触发时机时，回复 `[USE_SKILL:技能名]` 获取完整操作指南和脚本工具列表。"
        )
        return "\n".join(lines)

    @staticmethod
    def load_layer2_instruction(agent: "AgentModel", skill_name: str) -> str:
        """Layer 2: 加载 SKILL.md 完整正文 + 可执行工具列表"""
        skill = next((s for s in _active_skills(agent)
                      if s.name.lower() == skill_name.lower()), None)
        if not skill:
            return ""

        parts = [f"# 📋 技能「{skill.name}」完整操作指南\n"]

        # SKILL.md 指令正文
        if skill.instruction:
            parts.append(skill.instruction)

        # 列出可调用的脚本工具（含命令示例）
        if skill.script_dir:
            sd = os.path.join(skill.script_dir, "scripts")
            if os.path.isdir(sd):
                scripts = sorted(f for f in os.listdir(sd) if f.endswith(".py"))
                if scripts:
                    parts.append("\n## ⚡ 可执行工具（按 SKILL.md 命令格式调用）")
                    for sc in scripts:
                        tool = f"skill_{skill.name}_{sc.replace('.py', '').replace('.', '_')}"
                        fpath = os.path.join(sd, sc)
                        from engine.tools.registry import _extract_command_examples
                        examples = _extract_command_examples(
                            os.path.join(skill.script_dir, "SKILL.md"), sc
                        )
                        parts.append(f"### {tool}")
                        parts.append(f"执行脚本: `{skill.name}/scripts/{sc}`")
                        parts.append(f"调用方式: args 参数填命令行参数（不带 python3 {sc}）")
                        if examples:
                            parts.append(f"SKILL.md 示例:\n{examples}")
                        parts.append("")

        return "\n".join(parts)

    @staticmethod
    def detect_skill_request(response_text: str, agent: "AgentModel") -> str | None:
        """检测 LLM 回复中的 [USE_SKILL:name]"""
        m = re.search(r'\[USE_SKILL:\s*([^\]]+)\]', response_text, re.IGNORECASE)
        if not m:
            return None
        requested = m.group(1).strip()
        skills = _active_skills(agent)
        for s in skills:
            if s.name.lower() == requested.lower():
                return s.name
        for s in skills:
            if requested.lower() in s.name.lower() or s.name.lower() in requested.lower():
                return s.name
        return None

    @staticmethod
    def load_layer3_resources(skill_name: str, resource_type: str = "scripts") -> list[str]:
        base = os.path.join("skills_storage", skill_name, resource_type)
        if not os.path.isdir(base):
            return []
        resources = []
        for root, _, files in os.walk(base):
            for f in files:
                resources.append(os.path.join(root, f))
        return sorted(resources)
