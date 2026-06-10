from django import forms
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import Agent, AgentGroup, GroupNode, GroupEdge
from skills.models import Skill
from mcp_tools.models import MCPToolConfig


class AgentForm(forms.ModelForm):
    """自定义 Agent 表单 — 用 CheckboxSelectMultiple 渲染 M2M"""
    class Meta:
        model = Agent
        fields = ["name", "description", "system_prompt", "role", "agent_type", "group",
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


# ═══════════════════════════════════════════════════════════════════
# 群组管理视图
# ═══════════════════════════════════════════════════════════════════

class GroupListView(ListView):
    model = AgentGroup
    template_name = "groups/group_list.html"
    context_object_name = "groups"
    paginate_by = 15


class GroupCreateView(CreateView):
    model = AgentGroup
    template_name = "groups/group_form.html"
    fields = ["name", "description", "trigger_prompt", "is_active"]
    success_url = reverse_lazy("agents:group_list")


class GroupDetailView(DetailView):
    model = AgentGroup
    template_name = "groups/group_detail.html"
    context_object_name = "group"


class GroupDeleteView(DeleteView):
    model = AgentGroup
    template_name = "groups/group_confirm_delete.html"
    success_url = reverse_lazy("agents:group_list")


def group_editor(request, pk):
    """拓扑编辑器页面"""
    group = get_object_or_404(AgentGroup, pk=pk)
    available_agents = Agent.objects.filter(is_active=True)
    return render(request, "groups/group_editor.html", {
        "group": group,
        "available_agents": available_agents,
        "nodes": group.nodes.all(),
        "edges": group.edges.all(),
    })


def save_topology(request, pk):
    """保存拓扑 JSON"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    try:
        import json
        data = json.loads(request.body)
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edges", [])
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "无效的JSON"}, status=400)

    group = get_object_or_404(AgentGroup, pk=pk)

    if trigger_prompt:
        group.trigger_prompt = trigger_prompt
        group.save(update_fields=["trigger_prompt"])

    # 清除现有点线，重建
    group.nodes.all().delete()
    group.edges.all().delete()

    node_map = {}  # temp_id → real Node
    for n in nodes_data:
        node = GroupNode.objects.create(
            group=group,
            label=n.get("label", ""),
            node_type=n.get("node_type", "agent"),
            agent_id=n.get("agent_id") or None,
            config=n.get("config", {}),
            position_x=n.get("position_x", 0),
            position_y=n.get("position_y", 0),
        )
        node_map[n["temp_id"]] = node

    for e in edges_data:
        source = node_map.get(e.get("source_temp_id"))
        target = node_map.get(e.get("target_temp_id"))
        if source and target:
            GroupEdge.objects.create(
                group=group,
                source=source,
                target=target,
                label=e.get("label", ""),
                condition=e.get("condition", ""),
            )

    return JsonResponse({"ok": True, "nodes": nodes_data, "edges": edges_data})
