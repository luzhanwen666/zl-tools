from django.db import models


class LLMConfig(models.Model):
    """大模型配置"""

    PROVIDER_CHOICES = [
        ("anthropic", "Anthropic (Claude)"),
        ("openai", "OpenAI"),
        ("google", "Google (Gemini)"),
        ("deepseek", "DeepSeek"),
        ("ollama", "Ollama (本地)"),
        ("azure_openai", "Azure OpenAI"),
        ("other", "其他"),
    ]

    name = models.CharField("配置名称", max_length=200)
    provider = models.CharField("供应商", max_length=50, choices=PROVIDER_CHOICES)
    model_id = models.CharField("模型ID", max_length=200, help_text="如 claude-sonnet-4-6, gpt-4o")
    api_base = models.URLField("API地址", blank=True, default="")
    api_key = models.CharField("API Key", max_length=500, blank=True, default="")
    max_tokens = models.IntegerField("最大Token数", default=4096)
    temperature = models.FloatField("温度", default=0.7, help_text="0.0 ~ 2.0")
    is_default = models.BooleanField("默认配置", default=False)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "大模型配置"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.model_id})"
