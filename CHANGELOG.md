# 更新日志 (Changelog)

## 2026-06-10

### 多专家独立发言
- 协调者 prompt 重写，确保只说一句话分配任务，不替代专家分析
- 代码层强制：所有专家至少发言一次后才接受 [FINISH]
- 前端消息按角色区分：协调者蓝紫色、专家紫色，独立展示

### 上下文压缩
- system_prompt 截断 4000 字、单条消息 2000 字、历史消息 8 条
- ReAct 循环总大小超 10000 时自动保留 system + 最近 5 条
- max_tokens 限制 4096，防止 API 413/400 错误

---

## 2026-06-09

### Agent Skills 技能系统
- 新增 `Skill.script_dir` 和 `Skill.allowed_tools` 字段
- 技能 zip 导入保留完整目录结构，支持脚本执行
- 技能指令直接注入 system_prompt（不再作为可调用工具）
- 三层加载：Level 1(名+描述→协调者) + Level 2(完整指令→专家) + Level 3(脚本目录)
- 支持 SKILL.md YAML frontmatter 解析

### Shell & Python 工具
- 新增 `ShellTool`：跨平台命令执行（Windows PowerShell / Linux bash）
- 新增 `PythonExecutorTool`：执行 Python 代码
- 内置工具回归，所有 Agent 可用

### 多 Agent 协作优化
- 全局智能体路由：分类→匹配专家→群聊协作
- 前端专家芯片可点击手动选择
- 消息显示 🔧 工具调用标签
- 协调者不直接回答问题，必须通过专家

### LLM API 兼容性
- 移除消息中 `name` 字段（不兼容 DeepSeek）
- 工具结果使用 `role: "user"` 替代 `role: "tool"`
- 支持千问/DeepSeek/OpenAI 等多供应商

### 前端优化
- 首页 Hero 区域一键对话入口
- 输入框可打断流式对话
- Agent 表单可视化技能/Tool 选择
- LLM 配置表单修复 API Key 保存

### 会话记忆
- 群聊启动时加载最近 8 条历史消息作为上下文
- 会话间保持上下文连贯性

---

## 初始版本
- Django 6.0 多智能体协作平台
- GroupChatManager Round-Robin 群聊
- AgentRunner ReAct 执行器
- 统一 LLMClient 多供应商支持
- Agent/技能/LLM配置/MCP工具 CRUD
