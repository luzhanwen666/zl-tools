from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import Agent


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
    template_name = "agents/agent_form.html"
    fields = ["name", "description", "avatar", "system_prompt", "group", "role", "llm_config", "skills", "mcp_tools", "is_active"]

    def get_success_url(self):
        return reverse_lazy("agents:detail", kwargs={"pk": self.object.pk})


class AgentUpdateView(UpdateView):
    model = Agent
    template_name = "agents/agent_form.html"
    fields = ["name", "description", "avatar", "system_prompt", "group", "role", "llm_config", "skills", "mcp_tools", "is_active"]

    def get_success_url(self):
        return reverse_lazy("agents:detail", kwargs={"pk": self.object.pk})


class AgentDeleteView(DeleteView):
    model = Agent
    template_name = "agents/agent_confirm_delete.html"
    success_url = reverse_lazy("agents:list")
