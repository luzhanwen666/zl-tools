from django.db import models
from django.conf import settings


class ChatSession(models.Model):
    """对话会话"""

    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        verbose_name="智能体",
    )
    title = models.CharField("标题", max_length=200, blank=True, default="新对话")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="创建者",
    )

    class Meta:
        verbose_name = "对话会话"
        verbose_name_plural = verbose_name
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class ChatMessage(models.Model):
    """对话消息"""

    ROLE_CHOICES = [
        ("user", "用户"),
        ("assistant", "助手"),
        ("system", "系统"),
    ]

    MESSAGE_TYPE_CHOICES = [
        ("message", "对话"),
        ("thinking", "思考过程"),
        ("tool_call", "工具调用"),
        ("plan", "计划"),
        ("status", "状态"),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="会话",
    )
    role = models.CharField("角色", max_length=20, choices=ROLE_CHOICES)
    content = models.TextField("内容")
    agent_name = models.CharField("所属Agent", max_length=200, blank=True, default="")
    thinking = models.TextField("思考过程", blank=True, default="", help_text="存储中间推理（ReAct循环跟踪、反思笔记、计划步骤等）")
    stage = models.CharField("执行阶段", max_length=50, blank=True, default="",
                             help_text="planning/executing/reflecting/synthesizing/done")
    message_type = models.CharField("消息类型", max_length=30, choices=MESSAGE_TYPE_CHOICES, default="message")
    token_count = models.IntegerField("Token数量", null=True, blank=True)
    metadata = models.JSONField("元数据", blank=True, default=dict, help_text='存储工具调用、计划等中间数据')
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "对话消息"
        verbose_name_plural = verbose_name
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.role}] {self.content[:50]}"


class AgentPipeline(models.Model):
    """用户可配置的智能体执行流水线 — 定义专家执行顺序和依赖关系"""

    MODE_CHOICES = [
        ("sequential", "串行"),
        ("parallel", "并行"),
    ]

    name = models.CharField("流程名称", max_length=200, default="默认流程")
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="pipelines",
        verbose_name="会话",
    )
    steps = models.JSONField("执行步骤", default=list, help_text="""
        格式: [{"agent_name": "...", "order": 0, "depends_on": [], "mode": "sequential"}]
        depends_on: 依赖的agent_name列表，需等待这些agent完成后才能执行
        mode: sequential(等待上一步完成) 或 parallel(与上一步同时执行)
    """)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "执行流水线"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.session.title})"
