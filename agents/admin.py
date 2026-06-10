from django.contrib import admin
from .models import Agent


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "agent_type", "group", "is_global", "is_active", "llm_config", "created_at")
    list_filter = ("is_active", "is_global", "role", "agent_type", "group")
    search_fields = ("name", "description")
    filter_horizontal = ("skills", "mcp_tools")
    fieldsets = (
        ("基本信息", {"fields": ("name", "description", "avatar", "system_prompt")}),
        ("角色与协作", {"fields": ("role", "agent_type", "group", "is_global")}),
        ("配置", {"fields": ("llm_config", "skills", "mcp_tools")}),
        ("状态", {"fields": ("is_active", "created_by")}),
    )
