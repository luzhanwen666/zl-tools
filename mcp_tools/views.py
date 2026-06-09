from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import MCPToolConfig


class MCPToolConfigListView(ListView):
    model = MCPToolConfig
    template_name = "mcp_tools/mcptoolconfig_list.html"
    context_object_name = "tools"


class MCPToolConfigDetailView(DetailView):
    model = MCPToolConfig
    template_name = "mcp_tools/mcptoolconfig_detail.html"
    context_object_name = "tool"


class MCPToolConfigCreateView(CreateView):
    model = MCPToolConfig
    template_name = "mcp_tools/mcptoolconfig_form.html"
    fields = ["name", "description", "server_url", "transport", "env_vars", "args", "is_active"]

    def get_success_url(self):
        return reverse_lazy("mcp_tools:detail", kwargs={"pk": self.object.pk})


class MCPToolConfigUpdateView(UpdateView):
    model = MCPToolConfig
    template_name = "mcp_tools/mcptoolconfig_form.html"
    fields = ["name", "description", "server_url", "transport", "env_vars", "args", "is_active"]

    def get_success_url(self):
        return reverse_lazy("mcp_tools:detail", kwargs={"pk": self.object.pk})


class MCPToolConfigDeleteView(DeleteView):
    model = MCPToolConfig
    template_name = "mcp_tools/mcptoolconfig_confirm_delete.html"
    success_url = reverse_lazy("mcp_tools:list")
