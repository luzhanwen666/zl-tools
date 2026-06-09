from django.urls import path

from . import views

app_name = "mcp_tools"

urlpatterns = [
    path("", views.MCPToolConfigListView.as_view(), name="list"),
    path("create/", views.MCPToolConfigCreateView.as_view(), name="create"),
    path("<int:pk>/", views.MCPToolConfigDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.MCPToolConfigUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.MCPToolConfigDeleteView.as_view(), name="delete"),
]
