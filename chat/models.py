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

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="会话",
    )
    role = models.CharField("角色", max_length=20, choices=ROLE_CHOICES)
    content = models.TextField("内容")
    agent_name = models.CharField("所属Agent", max_length=200, blank=True, default="")
    token_count = models.IntegerField("Token数量", null=True, blank=True)
    metadata = models.JSONField("元数据", blank=True, default=dict, help_text='存储工具调用、计划等中间数据')
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "对话消息"
        verbose_name_plural = verbose_name
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.role}] {self.content[:50]}"
