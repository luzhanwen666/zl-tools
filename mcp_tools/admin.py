from django.contrib import admin
from .models import MCPToolConfig


@admin.register(MCPToolConfig)
class MCPToolConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "transport", "server_url", "is_active")
    list_filter = ("transport", "is_active")
    search_fields = ("name", "description")
