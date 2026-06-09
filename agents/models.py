from django.db import models
from django.conf import settings


class Agent(models.Model):
    """智能体"""

    ROLE_CHOICES = [
        ("coordinator", "协调者"),
        ("expert", "专家"),
        ("member", "成员"),
    ]

    name = models.CharField("名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    avatar = models.ImageField("头像", upload_to="avatars/", blank=True, null=True)
    system_prompt = models.TextField("系统提示词", blank=True, default="")
    group = models.CharField("协作组", max_length=100, blank=True, default="default")
    role = models.CharField("角色", max_length=50, choices=ROLE_CHOICES, default="member")
    llm_config = models.ForeignKey(
        "llm_config.LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="大模型配置",
    )
    skills = models.ManyToManyField(
        "skills.Skill",
        blank=True,
        related_name="agents",
        verbose_name="技能",
    )
    mcp_tools = models.ManyToManyField(
        "mcp_tools.MCPToolConfig",
        blank=True,
        related_name="agents",
        verbose_name="MCP工具",
    )
    is_active = models.BooleanField("是否启用", default=True)
    is_global = models.BooleanField(
        "全局智能体",
        default=False,
        help_text="作为平台全局入口的唯一智能体，用户对话均由此Agent统一接收和分发",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="创建者",
    )

    class Meta:
        verbose_name = "智能体"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
