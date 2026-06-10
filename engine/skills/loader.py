"""
Skills 渐进式加载器 — 按 Anthropic Agent Skills 规范实现三层渐进式披露

Layer 1（元数据）：启动时注入 system prompt，仅技能名称 + 描述，~100 tokens/技能
Layer 2（指令）：**LLM 主动请求**或**关键词触发**时加载完整 SOP
Layer 3（资源）：脚本已注册为工具，LLM 调用工具时自动执行

核心理念（来自 Extra05-AgentSkills解读.md）：
  Skills 是"操作手册"，告诉 LLM 如何做事；
  MCP/工具是"手"，让 LLM 能够做事。
  渐进式披露让 50 个技能仅消耗 ~5000 tokens（Layer 1），
  而非一次性加载所有完整指令导致上下文爆炸。
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.models import Agent as AgentModel

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 技能触发关键词表（用于 Layer 2 预加载）
# ═══════════════════════════════════════════════════════════════════

SKILL_TRIGGERS: dict[str, list[str]] = {
    "calculator": [
        "计算", "算式", "等于", "加", "减", "乘", "除",
        "平方", "开方", "sqrt", "sin", "cos", "tan", "log",
        "abs", "pow", "max", "min", "求和", "平均", "取整",
        "数学", "数值", "运算", "小数", "分数", "百分比",
    ],
    "waf-whitelist": [
        "加白", "加报", "whitelist", "白名单", "误报", "消除",
        "event_id", "eventid", "拦截", "waf", "误拦", "放行",
        "block", "false positive",
    ],
    "Firecrawl": [
        "抓取", "爬虫", "crawl", "scrape", "网页", "提取",
        "firecrawl", "markdown", "结构化", "内容提取", "网址",
    ],
    "AutoResearch": [
        "研究", "调研", "分析报告", "research", "综合", "归纳",
        "综述", "概览", "汇总", "调查", "竞品", "行业趋势",
    ],
    "Frontend Design": [
        "前端", "界面", "ui", "设计", "美化", "样式", "布局",
        "css", "html", "组件", "交互", "配色", "排版", "frontend",
    ],
    "Systematic Debugging": [
        "调试", "debug", "bug", "错误", "异常", "报错", "排查",
        "定位", "修复", "fix", "error", "traceback", "堆栈",
    ],
    "代码审查": [
        "代码审查", "code review", "审查", "重构", "optimize",
        "优化", "pep", "规范", "lint",
    ],
    "Superpowers": [
        "复杂", "多步骤", "高级", "增强", "规划", "自动化", "深度分析",
    ],
    # WAF 安全测试
    "waf-security-test": [
        "waf", "security", "test", "安全测试", "渗透", "绕过",
        "sql", "xss", "命令注入", "攻击向量", "防护", "扫描",
        "探测", "漏洞测试", "规则覆盖", "黑盒", "白盒",
    ],
    # WAF 样本测试
    "waf-sample-test": [
        "sample", "样本", "发包", "拦截率", "误报率", "漏报",
        "黑白样本", "检出率", "fuzz", "模糊测试",
    ],
}


def _active_skills(agent: "AgentModel") -> list:
    """获取活跃技能列表（内存过滤，无数据库查询）"""
    return [s for s in agent.skills.all() if s.is_active]


class SkillsLoader:
    """Agent Skills 渐进式披露加载器"""

    # ── Layer 1: 元数据 ──────────────────────────────────────────

    @staticmethod
    def load_layer1_metadata(agent: "AgentModel") -> str:
        """
        Layer 1：技能名称 + 简短描述，~100 tokens/技能。
        注入 system prompt，让 LLM 知道有哪些技能可用。
        同时告知 LLM：如需某技能的完整 SOP，回复 [USE_SKILL:name] 即可获取。
        """
        skills = _active_skills(agent)
        if not skills:
            return ""

        lines = ["## 可用技能（已加载元数据）"]
        for s in skills:
            desc = (s.description or "通用技能")[:70]
            lines.append(f"- **{s.name}**：{desc}")

        lines.append(
            f"\n💡 以上技能已载入元数据。如果当前任务需要某项技能的**完整操作指南（SOP）**，"
            f"在思考中输出 `[USE_SKILL:技能名]`，系统将立即加载该技能的详细指令和可执行脚本清单。"
        )
        return "\n".join(lines)

    # ── Layer 2: 完整指令 ────────────────────────────────────────

    @staticmethod
    def load_layer2_instruction(agent: "AgentModel", skill_name: str) -> str:
        """Layer 2：加载技能的完整 instruction 内容 + 脚本工具列表"""
        skill = next((s for s in _active_skills(agent)
                      if s.name.lower() == skill_name.lower()), None)
        if not skill:
            return ""

        parts = [f"# 📋 技能「{skill.name}」完整操作指南\n"]
        if skill.instruction:
            parts.append(skill.instruction)

        # 列出已注册的脚本工具
        if skill.script_dir:
            sd = os.path.join(skill.script_dir, "scripts")
            if os.path.isdir(sd):
                scripts = sorted(f for f in os.listdir(sd) if f.endswith(".py"))
                if scripts:
                    parts.append("\n## 可执行脚本（已注册为工具）")
                    for sc in scripts:
                        tool = f"skill_{skill.name}_{sc.replace('.py','').replace('.','_')}"
                        parts.append(f"- **{tool}** → `{skill.name}/scripts/{sc}`")

        if skill.allowed_tools:
            parts.append(f"\n## 允许使用的工具\n{skill.allowed_tools}")

        return "\n\n".join(parts)

    @staticmethod
    def load_all_layer2(agent: "AgentModel") -> str:
        """无精确匹配时加载所有技能 Layer 2 作为后备"""
        skills = _active_skills(agent)
        if not skills:
            return ""
        parts = []
        for s in skills:
            inst = SkillsLoader.load_layer2_instruction(agent, s.name)
            if inst:
                parts.append(inst)
        return "\n\n---\n\n".join(parts)

    # ── Layer 3: 附加资源 ────────────────────────────────────────

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

    # ── 技能匹配（关键词预加载 + LLM 主动触发） ─────────────────────

    @staticmethod
    def match_skill(user_message: str, agent: "AgentModel") -> str | None:
        """
        基于 SKILL_TRIGGERS 表进行关键词预匹配。
        命中则预加载 Layer 2，让 LLM 不需要手动 [USE_SKILL]。
        """
        skills = _active_skills(agent)
        if not skills:
            return None

        msg = user_message.lower()
        best: tuple[str, int] | None = None

        for s in skills:
            score = 0
            for kw in SKILL_TRIGGERS.get(s.name, []):
                if kw.lower() in msg:
                    score += 8
            # 技能名本身的单词命中
            for w in re.split(r'[-_\s]+', s.name.lower()):
                if len(w) > 2 and w in msg:
                    score += 5
            # 描述关键词
            for kw in (s.description or "").lower().split():
                if len(kw) > 2 and kw in msg:
                    score += 2

            if score > 0 and (best is None or score > best[1]):
                best = (s.name, score)

        if best:
            logger.info("Skill pre-matched: %s (score=%d)", best[0], best[1])
            return best[0]
        return None

    @staticmethod
    def detect_skill_request(response_text: str, agent: "AgentModel") -> str | None:
        """
        检测 LLM 回复中的 [USE_SKILL:name] 标记。
        这是**真正的渐进式披露 Layer 2 触发机制**：
        LLM 从 Layer 1 元数据看到有某技能 → 判断需要 → 主动请求加载。
        """
        m = re.search(r'\[USE_SKILL:\s*([^\]]+)\]', response_text, re.IGNORECASE)
        if not m:
            return None
        requested = m.group(1).strip()
        skills = _active_skills(agent)
        # 精确匹配
        for s in skills:
            if s.name.lower() == requested.lower():
                logger.info("LLM requested skill '%s' → loaded Layer 2", s.name)
                return s.name
        # 模糊匹配
        for s in skills:
            if requested.lower() in s.name.lower() or s.name.lower() in requested.lower():
                logger.info("LLM requested ~'%s' → matched '%s'", requested, s.name)
                return s.name
        logger.info("LLM requested unknown skill: %s", requested)
        return None
