---
name: waf-whitelist
description: 根据 WAF 拦截日志的 event_id 自动查询日志详情并生成加白规则，消除误报拦截
license: MIT
compatibility: opencode
---

## 功能说明

当用户提供一个 WAF 拦截事件的 `event_id`，自动完成以下流程：
1. 调用 FilterV2API 查询该事件的日志详情
2. 格式化展示攻击事件信息（攻击类型、源 IP、URL、策略模块等）
3. 基于日志字段构建精准加白规则并提交到对应接口

## 触发时机

用户说以下类似内容时使用此 skill：
- "帮我加白 event_id: xxxxxx"
- "这个事件是误报，event_id 是 xxxx"
- "消除误报 xxxx"
- "对 event_id xxxx 进行加白"
- "帮我加白 eventid: xxxxxx"
- "这个事件是误报，eventid 是 xxxx"
- "对id xxxx 进行加白"
- "对 xxx 进行加白"

## 环境配置

脚本从系统环境变量读取配置，无需修改代码：

- `BASE_URL`：WAF 服务地址，如 `https://192.168.24.55:9443`
- `API_TOKEN`：API 认证 Token

### 首次使用 / 环境变量缺失时的处理流程

如果运行脚本后输出 `[配置缺失]`，说明环境变量未设置。
此时需要询问用户：

> "请提供你的 WAF 地址和 API Token，我来帮你写入环境变量。"

用户提供后，执行以下命令将配置永久写入 shell 配置文件：

macOS 操作系统执行命令：

```bash
echo 'export BASE_URL="用户提供的地址"' >> ~/.zshrc
echo 'export API_TOKEN="用户提供的Token"' >> ~/.zshrc
source ~/.zshrc
```

CentOS 或 Ubuntu 操作系统执行命令：

```bash
echo 'export BASE_URL="用户提供的地址"' >> ~/.bashrc
echo 'export API_TOKEN="用户提供的Token"' >> ~/.bashrc
source ~/.bashrc
```

写入后重新执行加白命令即可，后续无需再次配置。

## 执行方式

从用户输入中提取 event_id，直接作为命令行参数传入。
如果用户明确指定了规则名称，通过 `--comment` 传入；否则不传，使用默认名称。
如果用户明确说"全局加白"，通过 `--global` 传入；否则默认绑定站点加白。

```bash
# 默认绑定站点加白
cd waf-whitelist/scripts && echo "y" | python3 main.py <event_id>

# 指定规则名称
cd waf-whitelist/scripts && echo "y" | python3 main.py <event_id> --comment "规则名称"

# 全局加白
cd waf-whitelist/scripts && echo "y" | python3 main.py <event_id> --global
```

示例：
- 用户说 "帮我加白 event_id: abc123" → `python3 main.py abc123`
- 用户说 "加白 abc123，规则名称叫做允许扫描器" → `python3 main.py abc123 --comment "允许扫描器"`
- 用户说 "全局加白 abc123" → `python3 main.py abc123 --global`

## 加白范围

默认绑定站点加白，若用户明确说"全局加白"则全局放行。

| 模式 | 触发条件 | `is_global` | `websites` |
|------|---------|-------------|------------|
| 绑定站点（默认） | 无特殊说明 | `false` | `[站点ID]` |
| 全局加白 | 用户说"全局加白" | `true` | `[]` |

绑定站点时需要：
1. 从日志 `website_name` 字段获取站点名称
2. 调用 `GET /api/FilterV2API?scope=detect:asset:site:all` 查询所有站点
3. 根据名称匹配对应站点 ID，填入 `websites: [id]`，`is_global` 设为 `false`
4. 若站点名称未匹配到，自动降级为全局加白

## 加白规则构建逻辑

从日志中提取以下字段构建 `$AND` 条件：

| 条件   | 匹配方式 | 来源字段 |
|--------|---------|---------|
| Method | 等于     | `method` |
| Host   | 等于     | `host` |
| URI    | 正则匹配 | `url_path`（仅路径部分，忽略 query string）|

URI 正则示例：
- `/` → `^/(\?.*)?$`
- `/admin/login?id=1` → `^/admin/login(\?.*)?$`

### 规则类型自动判断

根据日志字段自动选择 action 类型和接口，无需手动指定：

| 条件 | action | 接口 | 规则管理字段 |
|------|--------|------|------------|
| `req_rule_module == "m_rule"` 且 `req_skynet_rule_id_list` 有值 | `modify_skynet_rule` | `/api/ModifySkynetRulePolicyRuleAPI` | `skynet_rule_management.disabled: [规则ID]` |
| 其他情况 | `modify_module` | `/api/ModifyModulePolicyRuleAPI` | `module_management.disabled: [模块名]` |

示例：
- 检测模块拦截（如 XSS、SQL 注入）→ `modify_module`，disabled 填 `m_xss`、`m_sqli` 等
- 内置规则拦截（如后门检测）→ `modify_skynet_rule`，disabled 填 `req_skynet_rule_id_list` 中的规则 ID

## 预期输出

```
正在查询日志 event_id=xxxx ...
============================================================
【攻击事件详情】
  事件 ID        : xxxx
  攻击类型       : SQL Injection
  风险等级       : High（3级）
  ...
============================================================

正在提交加白规则...
  规则类型: 检测模块  module=m_sqli
  策略名称: 消除误报 - xxxx
  生成 URI 正则: ^/(\?.*)?$
  加白范围: 绑定站点 [53]
加白成功
```

## 注意事项

- 内网环境，已配置 `verify=False` 跳过 SSL 证书验证
- 备注自动填写为 `消除误报 - <event_id>`，可通过 `--comment` 覆盖
- 依赖：Python 3.9+，`pip install requests`
