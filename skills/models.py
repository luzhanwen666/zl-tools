from django.db import models


class Skill(models.Model):
    """技能 — 领域知识和操作规范的封装"""

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
    # 技能附带的脚本目录路径（zip 导入时保留完整目录结构）
    script_dir = models.CharField("脚本目录", max_length=500, blank=True, default="",
                                  help_text="技能 zip 解压后的目录路径，Agent 可执行其中的脚本")
    # 技能允许使用的工具白名单（逗号分隔，空=所有工具可用）
    allowed_tools = models.CharField("工具白名单", max_length=500, blank=True, default="",
                                     help_text="逗号分隔的工具名，仅列表中的工具对此技能可见")
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "技能"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
