"""
路由提示词 — 意图分类

采用 system + user 双层结构：
- system prompt = 强约束的分类规则（角色、规则、严禁事项）
- user prompt = 当前任务上下文（专家目录 + 用户消息）

同时提供关键词兜底匹配器，当 LLM 无法正确分类时自动降级匹配。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# System Prompt（强约束）
# ═══════════════════════════════════════════════════════════════════

CLASSIFIER_SYSTEM = """你是一个**严格的路由分类器**。你的唯一工作是：分析用户输入，从专家列表中选出最适合处理的专家。

## 🚨 铁律（违反将导致系统不可用）

1. **永远不要输出 is_general_question: true** —— 除非用户输入是纯粹的寒暄（"你好""在吗""谢谢"这种单句问候）。
2. **只要用户输入包含任何实质性内容（问题、请求、数据、链接、日志、代码、文件路径、URL、命令），必须匹配至少 1 位专家。**
3. **宁可多匹配几位专家，也绝不能漏匹配。匹配错了专家可以后续调整，但返回"无匹配"会导致用户无法使用。**
4. **专家名称必须从"可用专家"列表中逐字复制，不得自创。**

## 匹配策略（按优先级）

1. 从专家名称中提取关键词直接匹配：
   - 名称含"日志" → 日志类问题必匹配
   - 名称含"威胁""安全" → 安全类问题必匹配
   - 名称含"情报""查询" → 查询类问题必匹配
   - 名称含"计算""数学" → 计算类问题必匹配
   - 名称含"总结""报告" → 报告类问题必匹配

2. 从用户输入中识别领域信号：
   - HTTP请求/URL/路径遍历（/etc/passwd、../、cmd=） → 安全威胁 + 日志
   - IP地址/端口扫描/SQL注入/XSS → 安全威胁
   - 错误日志/异常堆栈/404/500 → 日志整理
   - 数字计算/表达式/数学问题 → 计算
   - 查询信息/搜索/百科 → 情报查询
   - 报告生成/事件汇总/总结 → 总结

3. 复杂任务匹配多个专家（按执行流程排序）

## 输出格式（严格 JSON，不要任何其他文字）

{"intent":"问题类别","recommended_agents":["专家1","专家2"],"is_general_question":false,"reasoning":"原因"}"""


# ═══════════════════════════════════════════════════════════════════
# User Prompt（当前任务）
# ═══════════════════════════════════════════════════════════════════

CLASSIFIER_USER = """## 可用专家列表
{agents_catalog}

## 用户输入
{user_message}

请严格按照 system prompt 中的规则，输出分类 JSON："""


# ═══════════════════════════════════════════════════════════════════
# 直接回复 / 结果合成（保持不变）
# ═══════════════════════════════════════════════════════════════════

GLOBAL_DIRECT_PROMPT = """你是「{agent_name}」，本平台的全局智能体。请你友好、专业地直接回答用户的问题。

## 回答要求
- 语言简洁清晰
- 如果有可用专家能更好地回答，请告知用户
- 保持友好的语气

用户问题：{user_message}"""


GLOBAL_SYNTHESIS_PROMPT = """你是「{agent_name}」，以下是各位专家对用户问题的独立分析：

## 用户问题
{user_question}

## 专家分析
{expert_analyses}

## 你的任务
请综合所有专家的分析，向用户提供清晰、完整的最终答案：
1. **核心结论**：一两句话概括最重要的发现
2. **要点汇总**：整理各专家的关键分析和建议
3. **分歧说明**：如果专家意见有分歧，客观说明
4. **行动建议**：基于综合分析的下一步建议"""


# ═══════════════════════════════════════════════════════════════════
# 消息构建
# ═══════════════════════════════════════════════════════════════════

def build_classifier_messages(agent_name: str, agents_catalog: str, user_message: str) -> list[dict]:
    """构建分类阶段的消息列表 — system + user 双层结构"""
    return [
        {"role": "system", "content": CLASSIFIER_SYSTEM},
        {"role": "user", "content": CLASSIFIER_USER.format(
            agents_catalog=agents_catalog,
            user_message=user_message,
        )},
    ]


def build_direct_messages(agent_name: str, system_prompt: str, user_message: str) -> list[dict]:
    """构建直接回复的消息列表"""
    return [
        {"role": "system", "content": system_prompt or f"你是{agent_name}，一个专业的智能助手。"},
        {"role": "user", "content": user_message},
    ]


def build_synthesis_messages(agent_name: str, chat_history: str) -> list[dict]:
    """构建结果合成的消息列表"""
    prompt = GLOBAL_SYNTHESIS_PROMPT.format(
        agent_name=agent_name,
        chat_history=chat_history,
    )
    return [{"role": "user", "content": prompt}]


# ═══════════════════════════════════════════════════════════════════
# 关键词兜底匹配器
# ═══════════════════════════════════════════════════════════════════

def keyword_fallback_match(user_message: str, agents_catalog: str) -> list[str]:
    """
    当 LLM 分类失败时，使用关键词进行兜底匹配。

    这会直接分析用户消息中的关键词，与专家名称/描述进行匹配。
    永远不会返回空列表（除非 agents_catalog 本身就是空的）。
    """
    msg_lower = user_message.lower()
    scored: list[tuple[str, int]] = []

    # 从 agents_catalog 中解析出专家名称和描述
    # 格式: "- **专家名**（角色·类型）：描述"
    agent_entries = re.findall(r'\*\*(.+?)\*\*（(.+?)）：(.+?)$', agents_catalog, re.MULTILINE)

    if not agent_entries:
        # 回退：只提取名称
        names = re.findall(r'\*\*(.+?)\*\*', agents_catalog)
        if names:
            return names[:3]
        return []

    for name, role_type, desc in agent_entries:
        score = 0
        combined = f"{name} {desc}".lower()

        # ── 加白/误报处理类 ──
        whitelist_pattern = (
            r'加白|加报|whitelist|白名单|误报|消除|event.?id|eventid|'
            r'拦截|block|误拦|误判|放行|pass|allow'
        )
        if re.search(whitelist_pattern, msg_lower):
            if '加白' in name or '加报' in name:
                score += 15
            if '白名单' in name or 'whitelist' in name.lower():
                score += 15
            if 'waf' in name.lower() or 'waf' in desc.lower():
                score += 8

        # ── 安全/威胁/攻击类 ──
        security_pattern = (
            r'攻击|威胁|入侵|漏洞|恶意|黑客|cve|exploit|payload|后门|webshell|'
            r'渗透|提权|反弹|shell|木马|病毒|钓鱼|ddos|扫描|暴力|'
            r'/etc/passwd|\.\./|cmd=|exec\(|system\(|whoami\b|id\b|uname|ls\b|'
            r'sql注入|xss|csrf|ssrf|命令执行|文件包含|反序列化|信息泄露|'
            r'sqli\b|xss\b|rce\b|lfi\b|ssrf\b|idor\b|ssi\b|'
            r'waf|ips|ids|防火墙|安全组|acl|态势|soar|soc|siem'
        )
        if re.search(security_pattern, msg_lower):
            if '威胁研判' in name:
                score += 10
            if '威胁' in name and '情报' not in name:
                score += 8
            if '安全' in name or '加白' in name:
                score += 5
            if '日志' in name:
                score += 4

        # ── 日志分析类 ──
        log_pattern = (
            r'日志|log|access|error|nginx|apache|tomcat|请求|响应|http|'
            r'状态码|status|404|500|403|200|302|ua\b|user.agent|referer|'
            r'时间戳|timestamp|来源|源\s*ip|目的|目标|端口|协议'
        )
        if re.search(log_pattern, msg_lower):
            if '日志整理' in name or '日志' in name:
                score += 8
            if '日志研判' in name:
                score += 6

        # ── 情报查询类 ──
        if re.search(r'查询|搜索|情报|百科|知识|谁|什么|哪里|了解|介绍|什么是', msg_lower):
            if '情报' in name or '查询' in name:
                score += 7

        # ── 计算类 ──
        if re.search(r'[\d\+\-\*/\(\)]{3,}|计算|等于|多少|加|减|乘|除|平方|开方|sqrt', msg_lower):
            if '计算' in name or '数学' in desc:
                score += 10

        # ── 总结/报告类 ──
        if re.search(r'总结|汇总|报告|归纳|整理|综述|概览', msg_lower):
            if '总结' in name or '报告' in name:
                score += 8

        # ── 通用：专家名中的词在用户消息中出现 ──
        name_words = re.findall(r'[一-鿿\w]+', name)
        for w in name_words:
            if len(w) >= 2 and w.lower() in msg_lower:
                score += 3

        if score > 0:
            scored.append((name, score))

    # 按分数降序排列
    scored.sort(key=lambda x: -x[1])

    if scored:
        logger.info("Keyword fallback matched: %s", [(n, s) for n, s in scored[:5]])
        return [name for name, _ in scored[:5]]

    # 真的没有任何匹配 → 返回空列表，交由 LLM 判定为通用问题
    logger.info("Keyword fallback found no matches — treating as general question")
    return []
