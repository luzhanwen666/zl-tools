from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    # 全局对话
    path("global/", views.global_chat, name="global_chat"),
    path("global/clear/<int:pk>/", views.clear_context, name="clear_context"),
    path("global/stream/", views.global_chat_send_message_stream, name="global_chat_stream"),
    path("global/send/", views.global_chat_send_message, name="global_chat_send"),

    # 工作流配置
    path("workflow/save/", views.save_workflow, name="save_workflow"),
    path("workflow/load/<int:pk>/", views.load_workflow, name="load_workflow"),
    path("workflow/delete/<int:pk>/", views.delete_workflow, name="delete_workflow"),

    # 对话历史 API（分页）
    path("sessions/api/", views.session_list_api, name="session_list_api"),

    path("bulk-delete/", views.session_bulk_delete, name="session_bulk_delete"),

    # 标准会话管理
    path("", views.ChatSessionListView.as_view(), name="session_list"),
    path("create/", views.ChatSessionCreateView.as_view(), name="session_create"),
    path("<int:pk>/", views.ChatSessionDetailView.as_view(), name="detail"),
    path("<int:pk>/delete/", views.ChatSessionDeleteView.as_view(), name="session_delete"),
    path("<int:pk>/send/", views.send_message, name="send_message"),
    path("<int:pk>/stream/", views.send_message_stream, name="send_message_stream"),
]
