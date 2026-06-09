from django.contrib import admin
from .models import ChatSession, ChatMessage


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "agent", "created_by", "updated_at")
    list_filter = ("agent",)
    search_fields = ("title",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "content_preview", "created_at")
    list_filter = ("role",)

    @admin.display(description="内容预览")
    def content_preview(self, obj):
        return obj.content[:80]
