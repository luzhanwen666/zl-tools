import os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'agent_platform.settings'
import django; django.setup()

from engine.llm_client import llm_client
from engine.schemas import AgentMessage, GroupChatState
from engine.tools.base import BaseTool, ToolRegistry, tool_registry
from engine.tools.registry import get_tools_for_agent
from engine.tools.builtin.log_parser import LogParserTool
from engine.tools.builtin.web_search import WebSearchTool
from engine.agent_runner import AgentRunner, _extract_tool_calls, _extract_json_objects
from engine.group_chat import GroupChatManager
from agents.models import Agent
from chat.models import ChatMessage

# 注册内置工具
tool_registry.register(LogParserTool())
tool_registry.register(WebSearchTool())
print("Registered tools:", [t.name for t in tool_registry.get_all()])

# 验证 Agent 组
group = Agent.objects.filter(group='security-analysis', is_active=True)
for a in group:
    print(f"  Agent: {a.name} ({a.role})")

# 验证字段
agent_fields = [f.name for f in Agent._meta.get_fields()]
msg_fields = [f.name for f in ChatMessage._meta.get_fields()]
assert 'group' in agent_fields
assert 'role' in agent_fields
assert 'agent_name' in msg_fields
assert 'metadata' in msg_fields

# 验证 GroupChatState
state = GroupChatState(speakers=['A', 'B'])
state.add_message(AgentMessage(role='user', content='hello', name='User'))
assert len(state.messages) == 1
assert state.get_current_speaker() == 'A'
state.advance_speaker()
assert state.get_current_speaker() == 'B'

# 验证工具调用解析
calls = _extract_tool_calls('Let me search. {"tool": "web_search", "args": {"query": "test"}}')
assert len(calls) == 1, f"Expected 1 tool call, got {len(calls)}"
assert calls[0].name == 'web_search'

# 验证嵌套 JSON 提取
json_objs = _extract_json_objects('text {"a": {"b": 1}} more {"x": 2} end')
assert len(json_objs) == 2

print("All checks passed!")
