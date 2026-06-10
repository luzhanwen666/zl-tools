"""
智能体引擎 - 数据结构定义
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentMessage:
    """智能体消息（Agent 间通信的基本单元）"""

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    name: str = ""  # 产生此消息的 Agent 名称
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: str = ""  # 对应的 tool call ID（用于 tool response）
    token_count: int | None = None
    metadata: dict = field(default_factory=dict)
    # metadata 可包含：thinking（思考追溯）、stage（执行阶段）、status_messages（状态）、agent_type

    def to_openai_message(self) -> dict:
        """转换为 OpenAI API 消息格式。不包含内部 tool_calls（格式不兼容）。"""
        msg: dict = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


@dataclass
class ToolCall:
    """工具调用信息"""

    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class GroupChatState:
    """群聊状态（所有 Agent 共享的上下文）"""

    messages: list[AgentMessage] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)  # Agent 名称列表
    speaker_roles: dict[str, str] = field(default_factory=dict)  # {agent_name: role}
    current_speaker_idx: int = 0  # 当前发言者索引
    max_rounds: int = 12  # 最大讨论轮次
    round_count: int = 0
    is_finished: bool = False
    plan: list[str] = field(default_factory=list)  # 分析计划
    findings: dict = field(default_factory=dict)  # 各 Agent 的发现

    def add_message(self, msg: AgentMessage):
        self.messages.append(msg)

    def get_openai_messages(self) -> list[dict]:
        """获取 OpenAI 格式的完整消息列表"""
        return [m.to_openai_message() for m in self.messages]

    def get_current_speaker(self) -> str:
        """获取当前发言者名称"""
        if not self.speakers:
            return ""
        return self.speakers[self.current_speaker_idx % len(self.speakers)]

    def advance_speaker(self):
        """轮转到下一个发言者"""
        self.current_speaker_idx = (self.current_speaker_idx + 1) % len(self.speakers)
        self.round_count += 1

    @property
    def should_continue(self) -> bool:
        """判断群聊是否应该继续"""
        if self.is_finished:
            return False
        if self.round_count >= self.max_rounds:
            return False
        return True

    def get_recent_messages(self, n: int = 20) -> list[AgentMessage]:
        """获取最近 n 条消息（控制上下文长度）"""
        return self.messages[-n:]
