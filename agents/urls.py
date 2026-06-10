from django.urls import path

from . import views

app_name = "agents"

urlpatterns = [
    path("", views.AgentListView.as_view(), name="list"),
    path("create/", views.AgentCreateView.as_view(), name="create"),
    path("<int:pk>/", views.AgentDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.AgentUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.AgentDeleteView.as_view(), name="delete"),

    # 群组管理
    path("groups/", views.GroupListView.as_view(), name="group_list"),
    path("groups/create/", views.GroupCreateView.as_view(), name="group_create"),
    path("groups/<int:pk>/", views.GroupDetailView.as_view(), name="group_detail"),
    path("groups/<int:pk>/edit/", views.group_editor, name="group_editor"),
    path("groups/<int:pk>/delete/", views.GroupDeleteView.as_view(), name="group_delete"),
    path("groups/<int:pk>/save-topology/", views.save_topology, name="save_topology"),
]
