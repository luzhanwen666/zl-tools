"""
Skills 渐进式加载器 — 全静态方法，不触发新 Django ORM 查询。
所有数据从已预加载的 Agent 关系中提取（prefetch_related("skills")）。
"""

from __future__ import annotations

import logging
import os
import re
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
        """关键词+正则匹配（V1.2），支持所有常见技能类型"""
        skills = _active_skills(agent)
        if not skills:
            return None

        msg = user_message.lower()
        best: tuple[str, int] | None = None

        for s in skills:
            score = 0
            sn = s.name.lower()

            # ── 通用：技能名中的单词出现在用户消息中 ──
            name_words = re.split(r'[-_\s]+', sn)
            for w in name_words:
                if len(w) >= 2 and w in msg:
                    score += 5

            # ── 描述中的关键词 ──
            desc_lower = (s.description or "").lower()
            for kw in desc_lower.split():
                if len(kw) >= 2 and kw in msg:
                    score += 1

            # ── 按技能名强制匹配（高优先级） ──
            # 计算类
            if any(kw in sn for kw in ["calculator", "calc", "计算", "算术"]):
                if re.search(r'[\d\+\-\*/\(\)]{2,}|计算|算式|等于|多少|加|减|乘|除|平方|开方|sqrt|pi|sin|cos|tan|log|abs|pow|max|min|求和|平均|取整', msg):
                    score += 25
                if re.search(r'\d+\s*[\+\-\*/]\s*\d+', msg):  # 数字运算表达式
                    score += 30

            # WAF/加白类
            if any(kw in sn for kw in ["waf", "whitelist", "加白", "加报", "白名单"]):
                if re.search(r'加白|加报|whitelist|白名单|误报|消除|event.?id|拦截|waf|误拦|放行|block|false.?positive', msg):
                    score += 25

            # 网页抓取类
            if any(kw in sn for kw in ["firecrawl", "crawl", "爬虫", "抓取", "提取"]):
                if re.search(r'抓取|爬虫|提取|crawl|scrape|网页|url|网站|firecrawl|markdown|内容提取|结构化', msg):
                    score += 25

            # 研究/报告类
            if any(kw in sn for kw in ["research", "研究", "auto", "自动研究"]):
                if re.search(r'研究|调研|报告|分析|research|综合|归纳|综述|概览|汇总|调查', msg):
                    score += 20

            # 前端设计类
            if any(kw in sn for kw in ["frontend", "design", "前端", "设计", "界面", "ui"]):
                if re.search(r'前端|界面|ui|设计|美化|样式|布局|css|html|页面|组件|交互|ux|配色|排版', msg):
                    score += 25

            # 调试类
            if any(kw in sn for kw in ["debug", "调试", "systematic"]):
                if re.search(r'调试|debug|bug|错误|异常|报错|排查|定位|修复|fix|error|traceback|堆栈', msg):
                    score += 25

            # 代码审查/编程类
            if any(kw in sn for kw in ["code", "代码", "审查", "编程"]):
                if re.search(r'代码|编程|写一个|实现|函数|类|import|def |class |review|审查|重构|优化|pep|规范', msg):
                    score += 22

            # Superpowers（通用增强）
            if any(kw in sn for kw in ["superpower", "super", "增强"]):
                if re.search(r'复杂|多步骤|高级|增强|super|规划|自动化|精通', msg):
                    score += 15

            # ── 分类关键词 ──
            cat_map = {
                "search": ["搜索", "查找", "查询", "检索"],
                "code": ["代码", "编程", "bug", "调试"],
                "data": ["数据", "分析", "统计", "SQL", "数据库"],
                "creative": ["创作", "文案", "设计"],
            }
            for kw in cat_map.get(s.category, []):
                if kw in msg:
                    score += 3

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
