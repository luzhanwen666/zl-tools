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
from django.views.generic.edit import FormMixin

from .models import ChatSession, ChatMessage

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

def _create_tool_registry():
    """创建并初始化工具注册中心（注册所有内置工具）。"""
    from engine.tools.base import ToolRegistry
    from engine.tools.builtin.log_parser import LogParserTool
    from engine.tools.builtin.web_search import WebSearchTool

    registry = ToolRegistry()
    registry.register(LogParserTool())
    registry.register(WebSearchTool())
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


class ChatSessionDetailView(DetailView, FormMixin):
    model = ChatSession
    template_name = "chat/session_detail.html"
    context_object_name = "session"
    form_class = None

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
    """渲染全局对话页面"""
    from agents.models import Agent

    global_agent = get_object_or_404(Agent, is_global=True, is_active=True)
    user = request.user if request.user.is_authenticated else None
    session, _ = ChatSession.objects.get_or_create(
        agent=global_agent,
        created_by=user,
        defaults={"title": "全局智能对话"},
    )

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
    """全局对话 - SSE 流式（线程+队列实现真正的流式推送，兼容 WSGI）"""
    from agents.models import Agent
    from engine.global_router import GlobalRouter

    global_agent = get_object_or_404(
        Agent.objects.filter(is_global=True, is_active=True)
        .select_related("llm_config").prefetch_related("skills", "mcp_tools"),
        is_global=True,
    )
    content = request.GET.get("content", "").strip() or (
        request.POST.get("content", "").strip() if request.method == "POST" else ""
    )
    if not content:
        return JsonResponse({"error": "消息不能为空"}, status=400)

    # 同步初始化（ORM 在主线程中安全执行）
    user = request.user if request.user.is_authenticated else None
    session, _ = ChatSession.objects.get_or_create(
        agent=global_agent, created_by=user,
        defaults={"title": "全局智能对话"},
    )
    ChatMessage.objects.create(session=session, role="user", content=content)

    def event_stream():
        yield f"data: {json.dumps({'type': 'user', 'content': content}, ensure_ascii=False)}\n\n"

        q: queue.Queue = queue.Queue()

        def _run_engine():
            """在独立线程中运行异步引擎，事件通过队列传出"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                registry = _create_tool_registry()
                router = GlobalRouter(tool_registry=registry)

                async def _stream():
                    try:
                        async for event in router.run_stream(session, content):
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
