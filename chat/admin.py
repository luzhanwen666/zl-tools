from django.contrib import admin
from .models import ChatSession, ChatMessage, AgentPipeline


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "agent", "created_by", "updated_at")
    list_filter = ("agent",)
    search_fields = ("title",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "message_type", "stage", "content_preview", "created_at")
    list_filter = ("role", "message_type")

    @admin.display(description="内容预览")
    def content_preview(self, obj):
        return obj.content[:80]


@admin.register(AgentPipeline)
class AgentPipelineAdmin(admin.ModelAdmin):
    list_display = ("name", "session", "is_active", "created_at")
    list_filter = ("is_active",)
