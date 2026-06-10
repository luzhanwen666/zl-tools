"""
智能体引擎 - ReflectionAgent 提示词模板

三阶段：Initial（生成初稿）→ Reflect（批判审视）→ Refine（改进答案）
"""

# ── 默认通用提示词 ──────────────────────────────────────────────────

REFLECTION_INITIAL_PROMPT = """请根据以下要求完成任务:

任务: {task}

请提供一个完整、准确的回答。"""

REFLECTION_CRITIQUE_PROMPT = """请仔细审查以下回答，并找出可能的问题或改进空间:

# 原始任务:
{task}

# 当前回答:
{content}

请分析这个回答的质量，指出不足之处，并提出具体的改进建议。
如果回答已经很好，请回答"无需改进"。"""

REFLECTION_REFINE_PROMPT = """请根据反馈意见改进你的回答:

# 原始任务:
{task}

# 上一轮回答:
{last_attempt}

# 反馈意见:
{feedback}

请提供一个改进后的回答。"""

# ── 代码生成专用提示词 ──────────────────────────────────────────────

REFLECTION_CODE_INITIAL = """你是Python专家，请编写函数: {task}"""

REFLECTION_CODE_CRITIQUE = """请审查以下代码的算法效率和正确性:

任务: {task}

代码:
{content}

请指出潜在的bug、性能问题、边界情况处理不足等问题。"""

REFLECTION_CODE_REFINE = """请根据以下审查意见优化代码:

任务: {task}

原始代码:
{last_attempt}

审查反馈:
{feedback}

请给出优化后的完整代码。"""

# ── 安全分析专用提示词 ──────────────────────────────────────────────

REFLECTION_SECURITY_INITIAL = """你是安全分析专家，请对以下信息进行安全评估: {task}"""

REFLECTION_SECURITY_CRITIQUE = """请审视以下安全分析，检查是否有遗漏的威胁面:

原始任务: {task}

当前分析:
{content}

请指出遗漏的攻击向量、误判的风险等级、或不够深入的分析点。"""

REFLECTION_SECURITY_REFINE = """请基于审查意见完善安全分析报告:

任务: {task}

初版分析: {last_attempt}

审查反馈: {feedback}

请给出完整、深入的安全分析报告。"""
