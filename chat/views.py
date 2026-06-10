import asyncio
import json
import logging
import queue
import threading

from asgiref.sync import async_to_sync
from django.contrib import messages
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, DeleteView

from .models import ChatSession, ChatMessage, AgentPipeline

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

def _create_tool_registry():
    """创建并初始化工具注册中心（注册所有内置工具）。"""
    from engine.tools.base import ToolRegistry
    from engine.tools.builtin.log_parser import LogParserTool
    from engine.tools.builtin.web_search import WebSearchTool
    from engine.tools.builtin.shell import ShellTool
    from engine.tools.builtin.python_executor import PythonExecutorTool

    registry = ToolRegistry()
    registry.register(LogParserTool())
    registry.register(WebSearchTool())
    registry.register(ShellTool())
    registry.register(PythonExecutorTool())
    return registry


def _save_chat_messages(session, messages: list):
    """批量保存消息到数据库。"""
    if not messages:
        return
    objs = []
    for msg in messages:
        objs.append(ChatMessage(
            session=session,
            role="assistant" if msg.role == "assistant" else msg.role,
            content=msg.content,
            agent_name=msg.name or "",
            metadata={"tool_calls": msg.tool_calls} if msg.tool_calls else {},
            token_count=msg.token_count,
        ))
    ChatMessage.objects.bulk_create(objs)
    logger.info("Saved %d messages for session %s", len(objs), session.pk)


# ------------------------------------------------------------------
# 标准会话视图
# ------------------------------------------------------------------

class ChatSessionListView(ListView):
    model = ChatSession
    template_name = "chat/session_list.html"
    context_object_name = "sessions"
    paginate_by = 15


class ChatSessionDetailView(DetailView):
    """对话页面：展示消息列表 + 发送消息表单"""
    model = ChatSession
    template_name = "chat/session_detail.html"
    context_object_name = "session"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["messages"] = self.object.messages.all()
        agent = self.object.agent
        if agent:
            from agents.models import Agent
            ctx["group_agents"] = list(
                Agent.objects.filter(group=agent.group, is_active=True)
                .values("name", "role", "avatar")
            )
        else:
            ctx["group_agents"] = []
        return ctx


class ChatSessionCreateView(CreateView):
    model = ChatSession
    template_name = "chat/session_form.html"
    fields = ["agent", "title"]

    def get_success_url(self):
        return reverse_lazy("chat:detail", kwargs={"pk": self.object.pk})


class ChatSessionDeleteView(DeleteView):
    model = ChatSession
    template_name = "chat/session_confirm_delete.html"
    success_url = reverse_lazy("chat:session_list")


def send_message(request, pk):
    """发送消息（同步方式）"""
    if request.method == "POST":
        session = get_object_or_404(ChatSession, pk=pk)
        content = request.POST.get("content", "").strip()
        if not content:
            return redirect("chat:detail", pk=pk)

        ChatMessage.objects.create(session=session, role="user", content=content)
        try:
            _run_group_chat(session, content)
        except Exception as e:
            logger.error("Group chat failed: %s", e)
            ChatMessage.objects.create(
                session=session, role="assistant",
                content=f"[系统错误] 群聊执行失败: {str(e)}"
            )
    return redirect("chat:detail", pk=pk)


def send_message_stream(request, pk):
    """发送消息（SSE 流式 — 线程+队列实现真正的流式推送）"""
    session = get_object_or_404(ChatSession, pk=pk)
    content = request.GET.get("content", "").strip() or request.POST.get("content", "").strip()
    if not content:
        return JsonResponse({"error": "消息不能为空"}, status=400)

    def event_stream():
        ChatMessage.objects.create(session=session, role="user", content=content)
        yield f"data: {json.dumps({'type': 'user', 'content': content}, ensure_ascii=False)}\n\n"

        q: queue.Queue = queue.Queue()

        def _run_engine():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                from engine.group_chat import GroupChatManager
                manager = GroupChatManager(tool_registry=_create_tool_registry())

                async def _stream():
                    try:
                        async for msg in manager.run_stream(session, content):
                            q.put(("msg", msg))
                    except Exception as e:
                        logger.exception("Stream error")
                        q.put(("error", str(e)))
                    finally:
                        q.put(("done", None))

                loop.run_until_complete(_stream())
            finally:
                loop.close()

        t = threading.Thread(target=_run_engine, daemon=True)
        t.start()

        all_messages = []
        while True:
            item = q.get()
            if item[0] == "done":
                break
            if item[0] == "error":
                yield f"data: {json.dumps({'type': 'error', 'content': item[1]}, ensure_ascii=False)}\n\n"
                break
            if item[0] == "msg":
                msg = item[1]
                all_messages.append(msg)
                data = {"type": "assistant", "content": msg.content, "agent_name": msg.name}
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        t.join(timeout=5)

        # 流结束，保存消息
        _save_chat_messages(session, all_messages)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _run_group_chat(session, content):
    """同步执行群聊"""
    from engine.group_chat import GroupChatManager
    manager = GroupChatManager(tool_registry=_create_tool_registry())
    all_messages = async_to_sync(manager.run)(session, content)
    _save_chat_messages(session, all_messages)


# ------------------------------------------------------------------
# 全局对话视图
# ------------------------------------------------------------------

def global_chat(request):
    """渲染全局对话页面。
    不带 session_id → 暂不创建会话（首次发消息时惰性创建）
    带 session_id  → 加载已有会话继续对话
    """
    from agents.models import Agent, AgentGroup

    # 启动检查：必须存在全局智能体且配置了模型
    global_agent = Agent.objects.filter(is_global=True, is_active=True).select_related("llm_config").first()
    if not global_agent or not global_agent.llm_config:
        return render(request, "chat/global_chat.html", {
            "session": None, "session_pk": 0, "global_agent": None,
            "all_agents": [], "available_groups": [],
            "startup_error": "⚠️ 系统未配置全局智能体，请先在「智能体」中创建一个全局智能体并配置大模型。",
        })
    user = request.user if request.user.is_authenticated else None

    session_id = request.GET.get("session_id", "").strip()
    if session_id:
        session = get_object_or_404(ChatSession, pk=session_id)
        session_pk = session.pk
    else:
        session = None
        session_pk = 0

    all_agents = list(
        Agent.objects.filter(is_active=True).values("name", "role", "description")
    )
    available_groups = list(
        AgentGroup.objects.filter(is_active=True).values("pk", "name", "description")
    )

    return render(request, "chat/global_chat.html", {
        "session": session,
        "session_pk": session_pk,
        "global_agent": global_agent,
        "all_agents": all_agents,
        "available_groups": available_groups,
    })


def clear_context(request, pk):
    """清空当前会话的上下文（删除所有消息）"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    session = get_object_or_404(ChatSession, pk=pk)
    session.messages.all().delete()
    return JsonResponse({"ok": True})

    all_agents = list(
        Agent.objects.filter(is_active=True).values("name", "role", "description")
    )

    return render(request, "chat/global_chat.html", {
        "session": session,
        "global_agent": global_agent,
        "all_agents": all_agents,
    })


def global_chat_send_message(request):
    """全局对话 - POST 发送（非流式）"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    from agents.models import Agent

    global_agent = get_object_or_404(Agent, is_global=True, is_active=True)
    content = request.POST.get("content", "").strip()
    if not content:
        return JsonResponse({"error": "消息不能为空"}, status=400)

    user = request.user if request.user.is_authenticated else None
    session, _ = ChatSession.objects.get_or_create(
        agent=global_agent, created_by=user,
        defaults={"title": "全局智能对话"},
    )

    ChatMessage.objects.create(session=session, role="user", content=content)

    try:
        from engine.global_router import GlobalRouter
        router = GlobalRouter(tool_registry=_create_tool_registry())
        all_messages = async_to_sync(router.run)(session, content)
        _save_chat_messages(session, all_messages)
    except Exception as e:
        logger.exception("Global chat failed")
        ChatMessage.objects.create(
            session=session, role="assistant",
            content=f"[系统错误] {str(e)}", agent_name="系统",
        )

    return redirect("chat:global_chat")


def global_chat_send_message_stream(request):
    """全局对话 - SSE 流式。
    group_id → 群组拓扑执行
    agents   → 手动选择专家
    无参数   → 全局智能体自动匹配群组场景（无匹配则拒绝回答）
    """
    from agents.models import Agent, AgentGroup
    from engine.global_router import GlobalRouter
    from engine.group_executor import GroupExecutor

    content = request.GET.get("content", "").strip()
    if not content:
        return JsonResponse({"error": "消息不能为空"}, status=400)

    group_id = request.GET.get("group_id", "").strip() or None
    manual_agents_str = request.GET.get("agents", "").strip() or None

    # session_id=0 → 惰性创建会话
    session_id = request.GET.get("session_id", "").strip()
    if session_id and session_id != "0":
        session = get_object_or_404(ChatSession, pk=session_id)
    else:
        global_agent = Agent.objects.filter(is_global=True, is_active=True).first()
        if not global_agent:
            return JsonResponse({"error": "全局智能体未配置，请联系管理员"}, status=500)
        user = request.user if request.user.is_authenticated else None
        session = ChatSession.objects.create(
            agent=global_agent, created_by=user, title=content[:40],
        )

    if not session.title or session.title == "新对话":
        session.title = content[:40]
        session.save(update_fields=["title"])

    # 手动选择的专家
    manual_agents = None
    if manual_agents_str:
        from agents.models import Agent as AgentModel
        agent_names = [a.strip() for a in manual_agents_str.split(",") if a.strip()]
        if agent_names:
            manual_agents = list(
                AgentModel.objects.filter(name__in=agent_names, is_active=True)
                .select_related("llm_config").prefetch_related("skills", "mcp_tools")
            )

    # ── 决定使用哪个群组 ──
    # 优先级: 手动选中群组 > 手动选中专家 > 自动匹配群组
    matched_group = None
    if group_id:
        matched_group = get_object_or_404(AgentGroup, pk=group_id, is_active=True)
    elif not manual_agents:
        available_groups = list(AgentGroup.objects.filter(is_active=True).exclude(trigger_prompt=""))
        if available_groups:
            loop = asyncio.new_event_loop()
            matched_id = loop.run_until_complete(
                _match_group_by_trigger(content, available_groups)
            )
            loop.close()
            if matched_id:
                matched_group = AgentGroup.objects.filter(pk=matched_id, is_active=True).first()
                if not matched_group:
                    matched_group = AgentGroup.objects.filter(pk=int(matched_id), is_active=True).first()

    # 无匹配且无人为选择 → 降级到原来的自动路由（GlobalOrchestrator）
    if not matched_group and not manual_agents:
        logger.info("No group matched, falling back to GlobalOrchestrator auto-routing")

    # 保存用户消息
    ChatMessage.objects.create(session=session, role="user", content=content)

    if matched_group:
        session.group = matched_group
        session.save(update_fields=["group"])
        # 同步预加载拓扑数据，避免 async 上下文触发懒查询
        _preloaded_nodes = list(matched_group.nodes.all().select_related(
            "agent", "agent__llm_config"
        ).prefetch_related("agent__skills", "agent__mcp_tools"))
        _preloaded_edges = list(matched_group.edges.all())
    else:
        _preloaded_nodes = []
        _preloaded_edges = []

    created_session_id = session.pk

    def event_stream():
        first_event = {'type': 'user', 'content': content}
        if created_session_id:
            first_event['session_id'] = created_session_id
        yield f"data: {json.dumps(first_event, ensure_ascii=False)}\n\n"

        # 提前告知前端当前执行模式
        if matched_group:
            yield f"data: {json.dumps({'type': 'routing', 'status': 'group', 'content': f'🔗 已匹配群组「{matched_group.name}」— 按拓扑顺序执行', 'group_name': matched_group.name}, ensure_ascii=False)}\n\n"

        q: queue.Queue = queue.Queue()

        def _run_engine():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                registry = _create_tool_registry()
                if matched_group:
                    group = matched_group
                    nodes = _preloaded_nodes
                    edges = _preloaded_edges
                    executor = GroupExecutor(tool_registry=registry)
                    async def _stream():
                        try:
                            async for event in executor.run_stream(session, content, group, nodes, edges):
                                q.put(("event", event))
                        except Exception as e:
                            logger.exception("GroupExecutor error")
                            q.put(("error", str(e)))
                        finally:
                            q.put(("done", None))
                else:
                    router = GlobalRouter(tool_registry=registry)
                    async def _stream():
                        try:
                            async for event in router.run_stream(session, content, manual_agents=manual_agents):
                                q.put(("event", event))
                        except Exception as e:
                            logger.exception("Engine stream error")
                            q.put(("error", str(e)))
                        finally:
                            q.put(("done", None))

                loop.run_until_complete(_stream())
            finally:
                loop.close()

        # 启动引擎线程
        t = threading.Thread(target=_run_engine, daemon=True)
        t.start()

        # 从队列中实时读取事件并 yield
        assistant_msgs = []
        while True:
            item = q.get()
            if item[0] == "done":
                break
            if item[0] == "error":
                yield f"data: {json.dumps({'type': 'error', 'content': item[1]}, ensure_ascii=False)}\n\n"
                break
            if item[0] == "event":
                event = item[1]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "assistant":
                    assistant_msgs.append(event)

        t.join(timeout=5)

        # 保存 assistant 消息到数据库（事件循环已结束，安全）
        if assistant_msgs:
            from engine.schemas import AgentMessage
            agent_msgs = [
                AgentMessage(role="assistant", content=m["content"], name=m.get("agent_name", ""))
                for m in assistant_msgs
            ]
            _save_chat_messages(session, agent_msgs)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# ------------------------------------------------------------------
# 群组匹配辅助
# ------------------------------------------------------------------

async def _match_group_by_trigger(user_message: str, available_groups) -> str | None:
    """
    使用全局智能体匹配用户输入与群组触发描述。
    返回匹配到的 group_id，或 None。
    """
    from agents.models import Agent
    global_agent = await Agent.objects.filter(is_global=True, is_active=True).select_related("llm_config").afirst()
    if not global_agent or not global_agent.llm_config:
        return None

    # 构建群组描述目录
    groups_desc = "\n".join(
        f"- **{g.name}** (ID:{g.pk}): {g.trigger_prompt or g.description}"
        for g in available_groups
    )

    prompt = (
        f"你是路由匹配器，根据用户输入选择最合适的群组。\n\n"
        f"## 可用群组及其触发场景\n{groups_desc}\n\n"
        f"## 用户输入\n{user_message}\n\n"
        f"## 匹配规则\n"
        f"1. 阅读每个群组的触发描述，判断用户需求与哪个群组最接近\n"
        f"2. **即使不完全匹配，也要选出描述最接近的一个群组**\n"
        f"3. 只输出最匹配的群组ID数字，不要输出任何其他内容\n"
        f"4. 示例：用户问'写一个Python程序'→如果某个群组描述为'处理日常问答和编程任务'则输出该群组ID"
    )

    from engine import llm_client as llm_module
    try:
        response = await llm_module.llm_client.chat(
            provider=global_agent.llm_config.provider,
            model_id=global_agent.llm_config.model_id,
            messages=[{"role": "user", "content": prompt}],
            api_base=global_agent.llm_config.api_base,
            api_key=global_agent.llm_config.api_key,
            max_tokens=50,
            temperature=0.0,
        )
    except Exception as e:
        logger.exception("Group trigger matching failed")
        return None

    response = response.strip().upper()
    if response == "NONE" or not response.isdigit():
        logger.info("No group matched: %s — will fallback to auto-routing", response[:50])
        return None

    matched_id = int(response)
    logger.info("Group matched: %d", matched_id)
    return str(matched_id)


# ------------------------------------------------------------------
# 工作流配置视图
# ------------------------------------------------------------------

def save_workflow(request):
    """保存流水线配置"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        import json
        data = json.loads(request.body)
        session_id = data.get("session_id")
        steps = data.get("steps", [])
        name = data.get("name", "默认流程")
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "无效的请求数据"}, status=400)

    session = get_object_or_404(ChatSession, pk=session_id)

    pipeline, created = AgentPipeline.objects.update_or_create(
        session=session, is_active=True,
        defaults={"name": name, "steps": steps},
    )

    return JsonResponse({
        "ok": True,
        "id": pipeline.pk,
        "created": created,
        "name": pipeline.name,
    })


def load_workflow(request, pk):
    """加载流水线配置"""
    pipeline = get_object_or_404(AgentPipeline, pk=pk, is_active=True)
    return JsonResponse({
        "id": pipeline.pk,
        "name": pipeline.name,
        "steps": pipeline.steps,
        "session_id": pipeline.session_id,
    })


def delete_workflow(request, pk):
    """删除流水线配置"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    pipeline = get_object_or_404(AgentPipeline, pk=pk)
    pipeline.is_active = False
    pipeline.save(update_fields=["is_active"])
    return JsonResponse({"ok": True})


# ------------------------------------------------------------------
# 对话历史 API（分页）
# ------------------------------------------------------------------

def session_list_api(request):
    """返回分页的对话历史 JSON"""
    page = int(request.GET.get("page", 1))
    per_page = 15
    user = request.user if request.user.is_authenticated else None

    qs = ChatSession.objects.filter(messages__isnull=False).distinct().order_by("-updated_at")
    if user:
        qs = qs.filter(created_by=user)
    total = qs.count()
    sessions = qs[(page - 1) * per_page : page * per_page]

    data = []
    for s in sessions:
        last_msg = s.messages.filter(role__in=("user", "assistant")).order_by("-created_at").first()
        data.append({
            "id": s.pk,
            "title": s.title or "新对话",
            "agent_name": s.agent.name if s.agent else "",
            "updated_at": s.updated_at.strftime("%m-%d %H:%M"),
            "last_message": last_msg.content[:60] if last_msg else "",
            "message_count": s.messages.count(),
        })

    return JsonResponse({
        "sessions": data,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    })


def session_bulk_delete(request):
    """批量删除会话"""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    try:
        ids = json.loads(request.body).get("ids", [])
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "无效的请求数据"}, status=400)
    if not ids:
        return JsonResponse({"error": "未提供会话ID"}, status=400)

    deleted, _ = ChatSession.objects.filter(pk__in=ids).delete()
    logger.info("Bulk deleted %d sessions: %s", deleted, ids)
    return JsonResponse({"ok": True, "deleted": deleted})
