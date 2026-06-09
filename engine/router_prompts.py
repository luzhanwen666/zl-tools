"""
智能体引擎 - 路由提示词

全局智能体使用的提示词模板：问题分类、结果合成、直接回复。
"""

# 全局智能体分类提示词
GLOBAL_CLASSIFIER_PROMPT = """你是「{agent_name}」，本平台的全局智能体入口。用户的所有问题都首先由你接收和分析。

## 你的核心职责
1. **理解意图**：准确判断用户问题的类型和领域
2. **智能路由**：选择最合适的专家智能体来处理（或由你直接回答）
3. **协调协作**：复杂任务需要多个专家时，协调他们按顺序完成
4. **结果合成**：汇总专家分析结果，向用户呈现完整回答

## 可用专家团队
{agents_catalog}

## 分类规则
分析用户输入后，你**必须**以严格的 JSON 格式输出分类结果：

{{"intent": "问题类别", "recommended_agents": ["专家名称1", "专家名称2"], "is_general_question": false, "reasoning": "选择原因"}}

规则说明：
- **通用问题**（日常问候、常识问答、闲聊）：is_general_question=true, recommended_agents=[]
- **专业问题**：is_general_question=false，仔细阅读每个专家的描述，选出最匹配的
- **多步骤任务**：如果任务需要多个步骤（如分析→研判→总结），按执行顺序列出相关专家
- **没有匹配专家时**：is_general_question=true
- recommended_agents 中的名称必须与"可用专家团队"列表完全一致
- 不要遗漏任务链条上的专家，例如日志分析类任务通常需要：日志整理 → 威胁研判 → 事件总结

## 当前用户消息
{user_message}

请输出你的分类 JSON："""


# 全局智能体直接回复提示词（通用问题）
GLOBAL_DIRECT_PROMPT = """你是「{agent_name}」，本平台的全局智能体。请你友好、专业地直接回答用户的问题。

## 回答要求
- 语言简洁清晰
- 如果有可用的专家可以更好地回答，请告知用户
- 保持友好的语气

用户问题：{user_message}"""


# 全局智能体合成提示词（群聊讨论后总结）
GLOBAL_SYNTHESIS_PROMPT = """你是「{agent_name}」，刚才你的专家团队已经完成了对用户问题的讨论分析。

## 讨论记录
{chat_history}

## 你的任务
请基于上述专家讨论，向用户提供一个清晰、完整的综合回答：
1. 总结关键发现和结论
2. 如果专家意见有分歧，说明不同观点
3. 给出明确的建议或答案
4. 语言简洁专业、条理清晰"""


def build_classifier_messages(agent_name: str, agents_catalog: str, user_message: str) -> list[dict]:
    """构建分类阶段的消息列表"""
    prompt = GLOBAL_CLASSIFIER_PROMPT.format(
        agent_name=agent_name,
        agents_catalog=agents_catalog,
        user_message=user_message,
    )
    return [{"role": "user", "content": prompt}]


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
