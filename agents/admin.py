from django.contrib import admin
from .models import Agent, AgentGroup, GroupNode, GroupEdge


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


@admin.register(AgentGroup)
class AgentGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")


@admin.register(GroupNode)
class GroupNodeAdmin(admin.ModelAdmin):
    list_display = ("label", "node_type", "group", "agent", "position_x", "position_y")
    list_filter = ("node_type", "group")
    search_fields = ("label",)


@admin.register(GroupEdge)
class GroupEdgeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "group", "condition")
    list_filter = ("group",)
