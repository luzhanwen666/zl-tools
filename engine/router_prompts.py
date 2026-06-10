"""
路由提示词 — 意图分类（通用，不依赖任何具体技能名）

classifier: system + user 双层结构，LLM 根据专家描述自主匹配
keyword_fallback: 通用领域→名称匹配，任何新导入技能都自动覆盖
"""

import logging
import re

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 分类提示词（通用 — 不列出任何具体技能名）
# ═══════════════════════════════════════════════════════════════════

CLASSIFIER_SYSTEM = """你是路由分类器。分析用户输入，从专家列表中选出最适合的专家。

## 铁律
1. 输入含任何实质性内容 → 必须匹配至少 1 位专家
2. 宁可多匹配，不能漏匹配
3. 专家名必须从列表中逐字复制

## 匹配策略
- **技能优先**：查看每位专家的技能标注（"技能: xxx"），用户需求匹配某技能 → 路由到有该技能的专家
- **描述匹配**：阅读专家描述，判断与用户意图的相关性
- **内容信号**：输入中的关键词（安全/日志/计算/测试/查询/加白/编程/设计等）→ 匹配描述中包含对应词的专家

## 输出格式（纯 JSON）
{"intent":"类别","recommended_agents":["专家1"],"is_general_question":false,"reasoning":"原因"}"""

CLASSIFIER_USER = """## 专家列表
{agents_catalog}

## 用户输入
{user_message}

输出分类 JSON："""

# ═══════════════════════════════════════════════════════════════════
# 直接回复 / 结果合成
# ═══════════════════════════════════════════════════════════════════

GLOBAL_DIRECT_PROMPT = """你是「{agent_name}」。友好专业地回答用户问题。
如有专家能更好地回答，请告知用户。

用户问题：{user_message}"""

GLOBAL_SYNTHESIS_PROMPT = """你是「{agent_name}」，以下是专家对用户问题的独立分析：

## 用户问题
{user_question}

## 专家分析
{expert_analyses}

## 你的任务
综合所有专家分析，提供清晰完整的最终答案：
1. 核心结论
2. 要点汇总
3. 分歧说明（如有）
4. 行动建议"""


def build_classifier_messages(agent_name: str, agents_catalog: str, user_message: str) -> list[dict]:
    return [
        {"role": "system", "content": CLASSIFIER_SYSTEM},
        {"role": "user", "content": CLASSIFIER_USER.format(
            agents_catalog=agents_catalog, user_message=user_message,
        )},
    ]


def build_direct_messages(agent_name: str, system_prompt: str, user_message: str) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt or f"你是{agent_name}，一个智能助手。"},
        {"role": "user", "content": user_message},
    ]


def build_synthesis_messages(agent_name: str, chat_history: str) -> list[dict]:
    prompt = GLOBAL_SYNTHESIS_PROMPT.format(
        agent_name=agent_name, chat_history=chat_history,
    )
    return [{"role": "user", "content": prompt}]


# ═══════════════════════════════════════════════════════════════════
# 通用关键词兜底匹配（领域→名称关联，不依赖任何具体技能名）
# ═══════════════════════════════════════════════════════════════════

_DOMAIN_PATTERNS: dict[str, str] = {
    "安全威胁": (
        r'攻击|威胁|入侵|漏洞|恶意|黑客|cve|exploit|payload|后门|webshell|'
        r'渗透|提权|反弹|木马|病毒|钓鱼|ddos|扫描|暴力|'
        r'/etc/passwd|\.\./|cmd=|exec\(|system\(|whoami\b|'
        r'sql注入|xss|csrf|ssrf|命令执行|文件包含|反序列化|信息泄露|'
        r'sqli\b|xss\b|rce\b|lfi\b|ssrf\b|idor\b|'
        r'waf|ips|ids|防火墙|安全组|acl|态势|soar|soc|siem'
    ),
    "日志分析": (
        r'日志|log|access|error|nginx|apache|tomcat|请求|响应|http|'
        r'状态码|status|404|500|403|302|ua\b|user.agent|referer|'
        r'时间戳|timestamp|来源|源\s*ip|目的|目标|端口|协议'
    ),
    "加白误报": (
        r'加白|加报|whitelist|白名单|误报|消除|event.?id|eventid|'
        r'拦截|block|误拦|误判|放行|pass|allow'
    ),
    "计算数学": r'[\d\+\-\*/\(\)]{3,}|计算|等于|多少|加|减|乘|除|平方|开方|sqrt|算式|运算|数学',
    "情报查询": r'查询|搜索|情报|百科|知识|了解|介绍|什么是|cve|漏洞',
    "代码编程": r'代码|编程|写一个|实现|函数|class|def |import |python|java|js|html|css|组件|api|重构|优化|review|审查',
    "前端设计": r'前端|界面|ui\b|设计|美化|样式|布局|css|组件|配色|排版|交互',
    "网页抓取": r'抓取|爬虫|crawl|scrape|网页|提取|markdown|结构化',
    "研究调研": r'研究|调研|分析报告|research|综合|归纳|综述|概览|汇总|调查|竞品',
    "调试排查": r'调试|debug|bug|错误|异常|报错|排查|定位|修复|fix|traceback|堆栈',
    "总结报告": r'总结|汇总|报告|归纳|整理|综述|概览',
    "WAF测试": r'waf.*测试|安全测试|security.*test|探测.*waf|扫描.*waf|绕过.*测试|fuzz|模糊测试|攻击测试',
}

_DOMAIN_NAME_KEYWORDS: dict[str, list[str]] = {
    "安全威胁": ["威胁", "安全", "sec", "hack", "攻击", "test", "测试"],
    "日志分析": ["日志", "log", "分析"],
    "加白误报": ["加白", "加报", "白名单", "whitelist", "waf"],
    "计算数学": ["计算", "数学", "calc", "math"],
    "情报查询": ["情报", "查询", "搜索", "intel", "search"],
    "代码编程": ["代码", "编程", "code", "程序", "开发"],
    "前端设计": ["前端", "frontend", "设计", "design", "界面", "ui"],
    "网页抓取": ["抓取", "爬虫", "crawl", "提取"],
    "研究调研": ["研究", "research", "分析", "调研", "auto"],
    "调试排查": ["调试", "debug", "排查", "fix"],
    "总结报告": ["总结", "报告", "汇总", "归纳"],
    "WAF测试": ["waf", "测试", "test", "security", "安全"],
}


def keyword_fallback_match(user_message: str, agents_catalog: str) -> list[str]:
    """
    通用兜底匹配：领域正则 → 专家名称关联。
    不依赖任何具体技能名 — 新导入的技能只要专家名称含对应关键词就能匹配。
    """
    msg_lower = user_message.lower()
    scored: dict[str, int] = {}

    names = re.findall(r'\*\*(.+?)\*\*', agents_catalog)
    if not names:
        return []

    # 1. 检测命中领域
    for domain, pattern in _DOMAIN_PATTERNS.items():
        if re.search(pattern, msg_lower):
            for kw in _DOMAIN_NAME_KEYWORDS.get(domain, []):
                for name in names:
                    if kw.lower() in name.lower():
                        scored[name] = scored.get(name, 0) + 8

    # 2. 专家名中的词直接命中用户消息
    for name in names:
        for w in re.findall(r'[\w一-鿿]{2,}', name):
            if w.lower() in msg_lower:
                scored[name] = scored.get(name, 0) + 5

    sorted_names = sorted(scored.items(), key=lambda x: -x[1])

    if sorted_names:
        logger.info("Fallback matched: %s", [(n, s) for n, s in sorted_names[:5]])
        return [n for n, _ in sorted_names[:5]]

    logger.info("Fallback: no match")
    return []
