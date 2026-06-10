# 更新日志 (Changelog)

## 2026-06-11

### 🏗️ 架构重构：独立分析 + 统一总结

彻底重写多 Agent 协作模式，从轮询群聊改为独立分析编排：

- **GlobalOrchestrator** — 新编排器，协调者分配任务 → 各专家独立完整执行 → 协调者一次性总结结束
- 不再进行无效的轮转讨论，每个专家运行完整执行策略（ReAct/Reflection/Plan&Solve）
- 保留旧版 GroupChatManager 向后兼容

### 🤖 4 种 Agent 执行类型

新增 `agent_type` 字段，创建 Agent 时可选择执行策略：

| 类型 | 说明 |
|------|------|
| **ReActAgent** 🔄 | Thought → Action → Observation 循环（默认） |
| **SimpleAgent** ⚡ | 单次 LLM 调用，直接问答 |
| **ReflectionAgent** 🪞 | Generate → Reflect → Refine 三阶段 |
| **PlanAndSolveAgent** 📋 | 先规划（分解步骤）→ 逐步执行 |

- 新增 `engine/executors/` 目录，包含 4 种执行器 + 调度工厂
- `AgentRunner` 重构为薄包装层，内部委托给对应 executor
- Agent 表单新增 agent_type 下拉框（含动态提示）

### 🔌 MCP 协议真实实现

从存根替换为完整的 JSON-RPC 2.0 通信：

- **MCPClient** (`engine/tools/mcp_client.py`) — 支持 Stdio 子进程 和 SSE 远程连接
- **MCPConnectionPool** — 按 MCPToolConfig ID 缓存连接，避免重复创建
- `MCPToolWrapper.execute()` 改为真实调用远程 MCP 工具
- 修复 Anthropic API URL 双重 `/v1/v1` 拼接错误

### 📋 Skills 渐进式披露实现

修复技能从未被实际匹配和注入的问题：

- **SkillsLoader** — 三层渐进式加载：Layer 1 元数据 → Layer 2 完整指令 → Layer 3 脚本资源
- `match_skill()` — 关键词匹配器，自动检测用户问题匹配最相关技能
- 修复异步上下文直接调用同步 ORM 导致的 `You cannot call this from an async context` 错误（内存过滤替代）
- 编排器 `_run_single_expert` 和 `_run_experts_stream` 集成技能匹配链路
- 前端展示技能使用标签 📋

### 🧠 分类路由强化

解决全局智能体无法识别专业问题：

- 分类提示词重写为 system + user 双层结构，system 注入铁律（`永远不要输出 is_general_question: true`）
- 温度降至 `0.0`，输出限制 `512` tokens
- **关键词兜底匹配器** — LLM 分类失败时自动用正则匹配（安全/日志/情报/计算/总结 5 大类）
- Agent 目录增强，附带 skills 和 mcp_tools 信息

### 🎨 前端全面升级

- **暗色终端风格** — 所有专家/协调者回复使用等宽字体暗色面板（`#0f172a`），与思考过程统一风格
- **JSON 自动格式化 + 语法高亮** — 键名蓝色、字符串绿色、数字黄色、布尔紫色
- **工作流配置面板** — 右侧滑出，拖拽排序 + 串行/并行切换，选中 ≥2 专家时自动显示入口
- **@提及协作** — 自动检测 `@AgentName` 并高亮对应专家芯片
- **思考过程实时展示** — 每步思考自动展开，最大 600px 高度可滚动
- **技能使用标签** — 专家回复头部显示蓝色技能标签
- 移除外部 JS/CSS 依赖，全部内嵌避免加载失败
- 修复表单提交双重事件绑定导致消息发送失败

### 🐛 Bug 修复

- 修复异步上下文调用同步 ORM 的错误
- 修复 LLM 分类 `is_general_question=true` 导致永远不匹配专家
- 修复 Anthropic URL 双重 `/v1/v1/messages` 拼接
- 修复 AgentPipeline 模型缺失 admin 注册

---

## 2026-06-10 (下午)

### 会话上下文管理
- 每次打开全局对话页创建新会话，不关联历史上下文
- 新增「🗑 清空上下文」按钮，一键删除当前会话消息
- 历史消息从 8 条减至 3 条，减少上下文累积

### Bug 修复
- 修复 `AgentMessage.tool_calls` 被发送到 LLM API 导致 400 错误
- 修复对话历史列表不显示全局对话记录
- 首次消息自动用问题内容做会话标题
- SSE 接口改用 session_id 参数定位会话
- 专家 prompt 增加工具调用 JSON 格式示例

---

## 2026-06-10 (上午)
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
