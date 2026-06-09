from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import Skill


class SkillListView(ListView):
    model = Skill
    template_name = "skills/skill_list.html"
    context_object_name = "skills"


class SkillDetailView(DetailView):
    model = Skill
    template_name = "skills/skill_detail.html"
    context_object_name = "skill"


class SkillCreateView(CreateView):
    model = Skill
    template_name = "skills/skill_form.html"
    fields = ["name", "description", "category", "instruction", "is_active"]

    def get_success_url(self):
        return reverse_lazy("skills:detail", kwargs={"pk": self.object.pk})


class SkillUpdateView(UpdateView):
    model = Skill
    template_name = "skills/skill_form.html"
    fields = ["name", "description", "category", "instruction", "is_active"]

    def get_success_url(self):
        return reverse_lazy("skills:detail", kwargs={"pk": self.object.pk})


class SkillDeleteView(DeleteView):
    model = Skill
    template_name = "skills/skill_confirm_delete.html"
    success_url = reverse_lazy("skills:list")
