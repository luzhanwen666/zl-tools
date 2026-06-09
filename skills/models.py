from django.db import models


class Skill(models.Model):
    """技能"""

    CATEGORY_CHOICES = [
        ("general", "通用"),
        ("search", "搜索"),
        ("code", "编程"),
        ("data", "数据处理"),
        ("creative", "创意"),
        ("other", "其他"),
    ]

    name = models.CharField("名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    category = models.CharField("分类", max_length=50, choices=CATEGORY_CHOICES, default="general")
    instruction = models.TextField("指令/提示词", blank=True, default="")
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "技能"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
