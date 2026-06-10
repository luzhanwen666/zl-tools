"""
Skills 渐进式加载器 — 全静态方法，不触发新 Django ORM 查询。
所有数据从已预加载的 Agent 关系中提取（prefetch_related("skills")）。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel

logger = logging.getLogger(__name__)


def _active_skills(agent: "AgentModel"):
    """获取 Agent 的活跃技能列表（内存过滤，不查数据库）。"""
    return [s for s in agent.skills.all() if s.is_active]


class SkillsLoader:
    """Agent Skills 渐进式披露加载器 — 异步安全"""

    @staticmethod
    def load_layer1_metadata(agent: "AgentModel") -> str:
        """Layer 1：技能名称 + 简短描述（~100 tokens/技能）"""
        skills = _active_skills(agent)
        if not skills:
            return ""

        lines = ["## 可用技能（可按需加载详细指令）"]
        for s in skills:
            desc = (s.description or "通用技能")[:80]
            emoji = {"search": "🔍", "code": "💻", "data": "📊",
                     "creative": "🎨", "general": "📋", "other": "🔧"}.get(s.category, "📋")
            lines.append(f"- {emoji} **{s.name}**: {desc}")

        lines.append(f"\n> 💡 当前激活 {len(skills)} 个技能，匹配任务后自动加载详细指令。")
        return "\n".join(lines)

    @staticmethod
    def load_layer2_instruction(agent: "AgentModel", skill_name: str) -> str:
        """Layer 2：完整技能指令（任务匹配时加载）"""
        skill = next((s for s in _active_skills(agent) if s.name == skill_name), None)
        if not skill:
            return ""

        parts = [f"## 📋 已激活技能: {skill.name}"]
        if skill.instruction:
            parts.append(skill.instruction)
        if skill.script_dir:
            parts.append(f"\n### 脚本资源\n脚本目录: `{skill.script_dir}`")
        if skill.allowed_tools:
            parts.append(f"\n### 工具白名单\n允许: {skill.allowed_tools}")

        parts.append("\n## ⚠️ 重要提醒\n技能中的代码示例是操作指南，你必须用 JSON 格式调用工具执行实际操作。")
        return "\n\n".join(parts)

    @staticmethod
    def load_all_layer2(agent: "AgentModel") -> str:
        """加载所有活跃技能的 Layer 2 指令"""
        skills = _active_skills(agent)
        if not skills:
            return ""

        parts = ["## 技能操作规范"]
        for s in skills:
            section = f"### {s.name}\n{s.instruction}"
            if s.script_dir:
                section += f"\n\n**脚本目录**: `{s.script_dir}`"
            if s.allowed_tools:
                section += f"\n**可用工具**: {s.allowed_tools}"
            parts.append(section)

        parts.append("\n## ⚠️ 技能示例是指导，用 JSON 工具调用执行实际操作。")
        return "\n\n".join(parts)

    # ── Layer 3: 按需资源 ─────────────────────────────────────────

    @staticmethod
    def load_layer3_resources(skill_name: str, resource_type: str = "scripts") -> list[str]:
        """返回技能附带的脚本/参考文件路径"""
        base_dir = os.path.join("skills_storage", skill_name, resource_type)
        if not os.path.isdir(base_dir):
            return []
        resources = []
        for root, _, files in os.walk(base_dir):
            for f in files:
                resources.append(os.path.join(root, f))
        return sorted(resources)

    # ── 技能匹配 ──────────────────────────────────────────────────

    @staticmethod
    def match_skill(user_message: str, agent: "AgentModel") -> str | None:
        """关键词匹配（V1），匹配到返回技能名称"""
        skills = _active_skills(agent)
        if not skills:
            return None

        msg = user_message.lower()
        best: tuple[str, int] | None = None

        for s in skills:
            score = 0
            for kw in s.name.lower().replace("-", " ").replace("_", " ").split():
                if len(kw) > 2 and kw in msg:
                    score += 5
            for kw in (s.description or "").lower().split():
                if len(kw) > 2 and kw in msg:
                    score += 1

            cat_map = {
                "search": ["搜索", "查找", "查询", "检索"],
                "code": ["代码", "编程", "bug", "调试"],
                "data": ["数据", "分析", "统计", "SQL", "数据库"],
                "creative": ["创作", "文案", "设计"],
            }
            for kw in cat_map.get(s.category, []):
                if kw in msg:
                    score += 3

            # ── WAF / 加白 / 误报 — 强制匹配 waf-whitelist 类技能 ──
            waf_kw = ["加白", "加报", "whitelist", "白名单", "误报", "消除",
                       "event_id", "eventid", "拦截", "waf", "误拦", "放行"]
            if any(kw in msg for kw in waf_kw):
                # 技能名含 waf 或 whitelist 或 加白 → 强制高分
                if any(kw in s.name.lower() for kw in ["waf", "whitelist", "加白", "加报"]):
                    score += 20
                # 描述含相关词
                if any(kw in (s.description or "").lower() for kw in
                       ["加白", "白名单", "whitelist", "waf", "误报", "拦截"]):
                    score += 12

            if score > 0 and (best is None or score > best[1]):
                best = (s.name, score)

        if best:
            logger.info("Skill matched: %s (score=%d)", best[0], best[1])
            return best[0]
        return None

    @staticmethod
    def match_all_skills(user_message: str, agent: "AgentModel") -> list[str]:
        """返回所有匹配到的技能名称（按得分排序）"""
        skills = _active_skills(agent)
        if not skills:
            return []

        msg = user_message.lower()
        scored = []
        for s in skills:
            score = 0
            for kw in s.name.lower().replace("-", " ").replace("_", " ").split():
                if len(kw) > 2 and kw in msg:
                    score += 5
            for kw in (s.description or "").lower().split():
                if len(kw) > 2 and kw in msg:
                    score += 1
            if score > 0:
                scored.append((s.name, score))

        scored.sort(key=lambda x: -x[1])
        return [name for name, _ in scored]
