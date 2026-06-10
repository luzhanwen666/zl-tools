# 🤖 智能体平台 (Agent Platform)

基于 Django 的多智能体协作平台，支持全局路由编排、4 种 Agent 执行类型、MCP 协议通信、渐进式技能加载、SSE 流式对话。

## 核心特性

- **全局智能体入口** — 一键对话，自动分析意图并匹配合适的专家团队
- **独立分析 + 统一总结** — 各专家独立完成完整分析，全局协调者一次性总结，**不进行无效轮询讨论**
- **4 种 Agent 执行类型** — ReAct（思考-行动循环）/ Simple（直接问答）/ Reflection（生成-反思-改进）/ Plan&Solve（先规划后执行）
- **Agent Skills 渐进式披露** — 三层加载（元数据 → 完整指令 → 脚本资源），每个技能仅 ~100 tokens 启动消耗
- **MCP 协议完整实现** — JSON-RPC 2.0 over Stdio / SSE，真实调用远程 MCP 工具
- **可配置执行流程** — 前端配置专家执行顺序，支持串行/并行切换
- **实时思考展示** — 暗色终端风格面板，JSON 自动高亮，@提及协作
- **SSE 流式对话** — 实时推送思考过程、工具调用、计划步骤，可打断
- **多 LLM 支持** — OpenAI / Anthropic / DeepSeek / Ollama / 千问 等，每位专家可绑定不同模型
- **会话上下文管理** — 新对话自动隔离上下文，一键清空历史

## 架构

```
用户输入
  ↓
GlobalRouter（意图分类 → 智能路由）
  ↓
GlobalOrchestrator（独立分析 + 统一总结）
  ├─ 协调者分配任务
  ├─ 专家A 独立完整执行（ReAct / Reflection / Plan&Solve）
  ├─ 专家B 独立完整执行
  └─ 协调者综合所有分析 → 最终答案
       ↑
  AgentExecutor（按 agent_type 分发）
  ├─ ReactExecutor    → Thought → Action → Observation
  ├─ SimpleExecutor   → 直接 LLM 调用
  ├─ ReflectionExecutor → Generate → Reflect → Refine
  └─ PlanAndSolveExecutor → Plan → Execute step by step
       ↑
  MCP Client（JSON-RPC 2.0） / Skills Loader（三层层进式）
```

## 快速开始

```bash
# 安装依赖
pip install django httpx asgiref aiohttp

# 初始化数据库
python manage.py migrate

# 启动服务
python manage.py runserver

# 访问
http://localhost:8000
```

## 项目结构

```
agent_platform/
├── agents/          # 智能体管理 (CRUD + agent_type + 全局入口)
├── chat/            # 对话会话 (SSE流式 + 工作流配置 + AgentPipeline)
├── skills/          # 技能管理 (SKILL.md导入 + 脚本目录)
├── llm_config/      # 大模型配置
├── mcp_tools/       # MCP工具配置 (Stdio/SSE)
├── engine/          # 核心引擎
│   ├── global_router.py      # 全局路由 + 关键词兜底匹配
│   ├── orchestrator.py       # GlobalOrchestrator 独立分析编排
│   ├── group_chat.py         # 群聊管理器（旧版轮询，向后兼容）
│   ├── agent_runner.py       # ReAct 执行器（委托给 executors）
│   ├── llm_client.py         # 统一 LLM 客户端（OpenAI/Anthropic）
│   ├── router_prompts.py     # 分类提示词 + 关键词兜底匹配器
│   ├── prompts.py            # 编排/反思/规划提示词模板
│   ├── schemas.py            # AgentMessage / AgentExecutionResult
│   ├── executors/            # Agent 执行器
│   │   ├── react_executor.py
│   │   ├── simple_executor.py
│   │   ├── reflection_executor.py
│   │   └── plan_and_solve_executor.py
│   ├── skills/               # 渐进式技能加载
│   │   ├── loader.py         # 3 层加载器 + 关键词匹配
│   │   └── script_executor.py
│   └── tools/                # 工具系统
│       ├── builtin/          # 内置工具 (shell, python, log_parser, web_search)
│       ├── registry.py       # 工具注册 + MCP 包装器
│       ├── mcp_client.py     # MCP JSON-RPC 2.0 客户端
│       └── mcp_pool.py       # MCP 连接池
└── templates/       # 前端模板 (Django + Vanilla JS)
```

## Agent 类型

| 类型 | 图标 | 执行策略 | 适用场景 |
|------|------|----------|---------|
| **ReAct** | 🔄 | Thought → Action → Observation 循环 | 需要工具调用的复杂任务 |
| **Simple** | ⚡ | 单次 LLM 调用 | 基础对话、常识问答 |
| **Reflection** | 🪞 | Generate → Reflect → Refine | 需要高质量输出的任务 |
| **Plan&Solve** | 📋 | 先分解任务为步骤，再逐步执行 | 复杂多步骤任务 |

## MCP 工具配置

支持两种传输方式：

- **Stdio** — 启动子进程，通过 stdin/stdout 进行 JSON-RPC 2.0 通信
- **SSE** — 连接远程 MCP Server，GET /sse 获取端点，POST 发送消息

```python
# 配置示例
MCPToolConfig.objects.create(
    name="高德地图",
    server_url="https://mcp.amap.com",
    transport="sse",        # sse 或 stdio
    env_vars={"API_KEY": "xxx"},
)
```

## 技能导入

支持标准 Agent Skills 格式的 zip 包导入：

```
skills.zip
├── skill-name/
│   ├── SKILL.md      # 主技能文件（YAML frontmatter + 指令）
│   └── scripts/      # 可执行脚本（可选）
└── ...
```

## License

MIT
