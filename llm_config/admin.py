from django.contrib import admin
from .models import LLMConfig


@admin.register(LLMConfig)
class LLMConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "model_id", "is_default", "is_active")
    list_filter = ("provider", "is_default", "is_active")
    search_fields = ("name", "model_id")
