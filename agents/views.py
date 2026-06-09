from django import forms
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import Agent
from skills.models import Skill
from mcp_tools.models import MCPToolConfig


class AgentForm(forms.ModelForm):
    """自定义 Agent 表单 — 用 CheckboxSelectMultiple 渲染 M2M"""
    class Meta:
        model = Agent
        fields = ["name", "description", "system_prompt", "role", "group",
                  "llm_config", "skills", "mcp_tools", "is_active", "is_global"]
        widgets = {
            "skills": forms.CheckboxSelectMultiple,
            "mcp_tools": forms.CheckboxSelectMultiple,
        }


class AgentListView(ListView):
    model = Agent
    template_name = "agents/agent_list.html"
    context_object_name = "agents"


class AgentDetailView(DetailView):
    model = Agent
    template_name = "agents/agent_detail.html"
    context_object_name = "agent"


class AgentCreateView(CreateView):
    model = Agent
    form_class = AgentForm
    template_name = "agents/agent_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["available_skills"] = Skill.objects.filter(is_active=True)
        ctx["available_mcp_tools"] = MCPToolConfig.objects.filter(is_active=True)
        return ctx

    def get_success_url(self):
        return reverse_lazy("agents:detail", kwargs={"pk": self.object.pk})


class AgentUpdateView(UpdateView):
    model = Agent
    form_class = AgentForm
    template_name = "agents/agent_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["available_skills"] = Skill.objects.filter(is_active=True)
        ctx["available_mcp_tools"] = MCPToolConfig.objects.filter(is_active=True)
        return ctx

    def get_success_url(self):
        return reverse_lazy("agents:detail", kwargs={"pk": self.object.pk})


class AgentDeleteView(DeleteView):
    model = Agent
    template_name = "agents/agent_confirm_delete.html"
    success_url = reverse_lazy("agents:list")
