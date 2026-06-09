# 🤖 智能体平台 (Agent Platform)

基于 Django 6.0 的多智能体协作平台，支持全局路由、群聊协作、技能系统、Shell/Python 工具执行。

## 核心特性

- **全局智能体入口** — 一键对话，自动分析意图并匹配合适的专家团队
- **多 Agent 群聊协作** — Round-Robin 轮转发言，每个专家的分析独立可见
- **Agent Skills 技能系统** — 支持标准 SKILL.md 格式，渐进式三层加载
- **Shell/Python 工具** — Agent 可直接执行系统命令和 Python 脚本
- **SSE 流式对话** — 实时推送，可打断补充信息
- **会话上下文管理** — 新对话自动隔离上下文，一键清空历史
- **多 LLM 支持** — OpenAI / DeepSeek / Anthropic / Ollama / 千问 等

## 架构

```
用户输入 → GlobalRouter(分类路由) → GroupChatManager(轮转群聊) → AgentRunner(ReAct执行)
                │                        │                           │
          全局智能体                协调者 + 专家们              LLM + 工具调用
```

## 快速开始

```bash
# 安装依赖
pip install django httpx asgiref

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
├── agents/          # 智能体管理 (CRUD + 全局入口)
├── chat/            # 对话会话 (SSE流式 + 上下文记忆)
├── skills/          # 技能管理 (SKILL.md导入 + 脚本目录)
├── llm_config/      # 大模型配置
├── mcp_tools/       # MCP工具配置
├── engine/          # 核心引擎
│   ├── global_router.py    # 全局路由
│   ├── group_chat.py       # 群聊管理器
│   ├── agent_runner.py     # ReAct执行器
│   ├── llm_client.py       # 统一LLM客户端
│   ├── prompts.py          # 提示词模板
│   └── tools/              # 工具系统
│       ├── builtin/        # 内置工具 (shell, python, log_parser, web_search)
│       └── registry.py     # 工具注册
└── templates/       # 前端模板
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
