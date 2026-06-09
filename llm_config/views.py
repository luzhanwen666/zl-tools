from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from .models import LLMConfig

import httpx
import logging
import re

logger = logging.getLogger(__name__)


# 供应商自动识别规则
PROVIDER_PATTERNS = {
    "anthropic": ["anthropic", "claude"],
    "openai": ["openai", "api.openai"],
    "deepseek": ["deepseek"],
    "ollama": ["localhost:11434", "ollama"],
    "azure_openai": ["azure", "openai.azure"],
    "google": ["generativelanguage", "gemini", "palm"],
}


def _guess_provider(api_base: str) -> str:
    """根据 API 地址自动推测供应商"""
    base = api_base.lower().rstrip("/")
    for provider, keywords in PROVIDER_PATTERNS.items():
        for kw in keywords:
            if kw in base:
                return provider
    return "other"


class LLMConfigListView(ListView):
    model = LLMConfig
    template_name = "llm_config/llmconfig_list.html"
    context_object_name = "configs"


class LLMConfigDetailView(DetailView):
    model = LLMConfig
    template_name = "llm_config/llmconfig_detail.html"
    context_object_name = "config"


class LLMConfigCreateView(CreateView):
    model = LLMConfig
    template_name = "llm_config/llmconfig_form.html"
    fields = ["name", "provider", "model_id", "api_base", "api_key", "max_tokens", "temperature", "is_default", "is_active"]

    def get_initial(self):
        """预设表单初始值"""
        initial = super().get_initial()
        if "model_id" not in initial or not initial["model_id"]:
            initial["model_id"] = ""
        return initial

    def form_invalid(self, form):
        """表单验证失败时保留用户已输入的数据"""
        messages.error(self.request, "请填写所有必填字段")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy("llm_config:detail", kwargs={"pk": self.object.pk})


class LLMConfigUpdateView(UpdateView):
    model = LLMConfig
    template_name = "llm_config/llmconfig_form.html"
    fields = ["name", "provider", "model_id", "api_base", "api_key", "max_tokens", "temperature", "is_default", "is_active"]

    def form_invalid(self, form):
        messages.error(self.request, "请填写所有必填字段")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy("llm_config:detail", kwargs={"pk": self.object.pk})


class LLMConfigDeleteView(DeleteView):
    model = LLMConfig
    template_name = "llm_config/llmconfig_confirm_delete.html"
    success_url = reverse_lazy("llm_config:list")


def fetch_models(request):
    """通过 API Base URL 和 Key 自动获取可用模型列表"""
    api_base = request.GET.get("api_base", "").strip().rstrip("/")
    api_key = request.GET.get("api_key", "").strip()

    if not api_base:
        return JsonResponse({"error": "请输入 API 地址"}, status=400)

    # 规范化：去掉末尾的 /v1 避免拼接后变成 /v1/v1
    api_base = re.sub(r"/v1/?$", "", api_base)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{api_base}/v1/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("data", []):
            models.append({
                "id": m.get("id", ""),
                "name": m.get("id", ""),  # 大多数 API 的 id 就是名称
            })

        # 自动推测供应商
        provider = _guess_provider(api_base)

        return JsonResponse({"models": models, "provider": provider})

    except httpx.ConnectError:
        return JsonResponse({"error": f"无法连接到 {api_base}"}, status=400)
    except httpx.TimeoutException:
        return JsonResponse({"error": "连接超时，请检查 API 地址"}, status=400)
    except Exception as e:
        logger.exception("Fetch models failed")
        return JsonResponse({"error": f"获取模型失败: {str(e)}"}, status=400)
