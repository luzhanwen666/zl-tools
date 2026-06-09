from django.urls import path

from . import views

app_name = "llm_config"

urlpatterns = [
    path("", views.LLMConfigListView.as_view(), name="list"),
    path("create/", views.LLMConfigCreateView.as_view(), name="create"),
    path("<int:pk>/", views.LLMConfigDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.LLMConfigUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.LLMConfigDeleteView.as_view(), name="delete"),
    path("fetch-models/", views.fetch_models, name="fetch_models"),
]
