from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from chat.models import ChatSession


def home_view(request):
    sessions = ChatSession.objects.select_related("agent").order_by("-updated_at")[:10]
    return TemplateView.as_view(
        template_name="home.html",
        extra_context={"recent_sessions": sessions},
    )(request)


urlpatterns = [
    path("", home_view, name="home"),
    path("admin/", admin.site.urls),
    path("agents/", include("agents.urls")),
    path("skills/", include("skills.urls")),
    path("chat/", include("chat.urls")),
    path("llm/", include("llm_config.urls")),
    path("mcp/", include("mcp_tools.urls")),
]
