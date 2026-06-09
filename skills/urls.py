from django.urls import path

from . import views

app_name = "skills"

urlpatterns = [
    path("", views.SkillListView.as_view(), name="list"),
    path("create/", views.SkillCreateView.as_view(), name="create"),
    path("<int:pk>/", views.SkillDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.SkillUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.SkillDeleteView.as_view(), name="delete"),
]
