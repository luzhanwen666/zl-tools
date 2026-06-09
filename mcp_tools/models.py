from django.db import models


class MCPToolConfig(models.Model):
    """MCP工具配置"""

    TRANSPORT_CHOICES = [
        ("stdio", "Stdio"),
        ("sse", "SSE (Server-Sent Events)"),
    ]

    name = models.CharField("工具名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    server_url = models.CharField("服务地址", max_length=500, help_text="Stdio: 命令路径; SSE: HTTP地址")
    transport = models.CharField("传输方式", max_length=20, choices=TRANSPORT_CHOICES, default="stdio")
    env_vars = models.JSONField("环境变量", blank=True, default=dict, help_text='如 {"API_KEY": "xxx"}')
    args = models.JSONField("启动参数", blank=True, default=list, help_text='如 ["--port", "8080"]')
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "MCP工具配置"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
