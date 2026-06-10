from django.db import models
from django.conf import settings


class AgentGroup(models.Model):
    """Agent 群组 — 拓扑工作流的基本单元"""

    name = models.CharField("群组名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    trigger_prompt = models.TextField(
        "触发描述", blank=True, default="",
        help_text="描述什么场景下应触发此群组，全局智能体根据用户输入匹配。例如：\"当用户请求WAF安全测试或站点漏洞扫描时触发\""
    )
    match_prompt = models.TextField(
        "匹配提示词", blank=True, default="",
        help_text="自定义本群组的匹配提示词，为空则使用全局默认。可包含 {group_name}、{group_desc}、{user_message} 变量"
    )
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "Agent群组"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Agent(models.Model):
    """智能体"""

    ROLE_CHOICES = [
        ("coordinator", "协调者"),
        ("expert", "专家"),
        ("member", "成员"),
    ]

    AGENT_TYPE_CHOICES = [
        ("react", "ReActAgent - 思考行动观察循环"),
        ("simple", "SimpleAgent - 直接问答"),
        ("reflection", "ReflectionAgent - 生成反思改进"),
        ("plan_and_solve", "PlanAndSolveAgent - 先规划后执行"),
    ]

    name = models.CharField("名称", max_length=200)
    description = models.TextField("描述", blank=True, default="")
    avatar = models.ImageField("头像", upload_to="avatars/", blank=True, null=True)
    system_prompt = models.TextField("系统提示词", blank=True, default="")
    group = models.ForeignKey(
        "AgentGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="所属群组",
    )
    role = models.CharField("角色", max_length=50, choices=ROLE_CHOICES, default="member")
    agent_type = models.CharField(
        "智能体类型", max_length=30,
        choices=AGENT_TYPE_CHOICES, default="react",
        help_text="决定Agent的执行策略：ReAct循环/直接问答/反思改进/先规划后执行",
    )
    llm_config = models.ForeignKey(
        "llm_config.LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="大模型配置",
    )
    skills = models.ManyToManyField(
        "skills.Skill",
        blank=True,
        related_name="agents",
        verbose_name="技能",
    )
    mcp_tools = models.ManyToManyField(
        "mcp_tools.MCPToolConfig",
        blank=True,
        related_name="agents",
        verbose_name="MCP工具",
    )
    is_active = models.BooleanField("是否启用", default=True)
    is_global = models.BooleanField(
        "全局智能体",
        default=False,
        help_text="作为平台全局入口的唯一智能体，用户对话均由此Agent统一接收和分发",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="创建者",
    )

    class Meta:
        verbose_name = "智能体"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class GroupNode(models.Model):
    """群组拓扑节点 — Agent 节点或基础逻辑组件"""

    NODE_TYPE_CHOICES = [
        ("start", "开始"),
        ("agent", "智能体"),
        ("condition", "条件判断"),
        ("loop", "循环控制"),
        ("parallel", "并行分发"),
        ("merge", "结果合并"),
        ("end", "结束"),
    ]

    group = models.ForeignKey("AgentGroup", on_delete=models.CASCADE, related_name="nodes")
    label = models.CharField("节点标签", max_length=200)
    node_type = models.CharField("节点类型", max_length=20, choices=NODE_TYPE_CHOICES, default="agent")
    agent = models.ForeignKey(
        "Agent", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="node_type=agent 时绑定具体智能体",
    )
    config = models.JSONField("节点配置", default=dict, blank=True,
                               help_text='条件表达式，循环次数等。如 {"condition":"success","max_loops":3}')
    position_x = models.FloatField("X坐标", default=0)
    position_y = models.FloatField("Y坐标", default=0)

    class Meta:
        verbose_name = "拓扑节点"
        verbose_name_plural = verbose_name
        ordering = ["group", "position_y", "position_x"]

    def __str__(self):
        return f"{self.label} ({self.get_node_type_display()})"


class GroupEdge(models.Model):
    """拓扑连线"""

    group = models.ForeignKey("AgentGroup", on_delete=models.CASCADE, related_name="edges")
    source = models.ForeignKey("GroupNode", on_delete=models.CASCADE, related_name="outgoing_edges")
    target = models.ForeignKey("GroupNode", on_delete=models.CASCADE, related_name="incoming_edges")
    label = models.CharField("连线标签", max_length=100, blank=True, default="")
    condition = models.CharField("触发条件", max_length=300, blank=True, default="",
                                  help_text="条件分支时使用，如 'success' / 'failure'")

    class Meta:
        verbose_name = "拓扑连线"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.source.label} → {self.target.label}"
