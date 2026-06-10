---
name: waf-security-test
description: 对指定站点 URL 执行 WAF 安全功能测试，覆盖 SQL 注入、XSS、文件包含等 23 类攻击用例，返回每项测试结果和对应的拦截 event_id。测试完成后可选执行 WAF 日志截图和生成 Word 测试报告。
license: MIT
compatibility: opencode
---

## 功能说明

对用户提供的目标站点 URL 发起全套 WAF 攻击测试，输出每个测试用例的拦截状态和 event_id。

测试覆盖范围（23 项）：
SQL 注入、XSS 攻击、Java 反序列化、文件上传、文件包含、PHP 代码注入、CSRF、SSRF、
PHP 反序列化、ASP 攻击、Java 代码注入、命令注入、情报模块、服务器响应、机器人检测、
Base64 编码绕过、URL 编码绕过、JSON 解析攻击、16 进制编码、反斜杠转义、XML 编码、
UTF-7 编码、多层编码解析

测试完成后，可选择：
1. **日志截图** — 自动登录 WAF 面板，逐个访问拦截事件的详情页并截图
2. **生成报告** — 将截图插入 Word 测试报告模板

---

## Phase 1: 攻击测试

### 触发时机

用户说以下类似内容时使用此 skill：
- "帮我测试一下这个站点 http://xxx"
- "对 http://xxx 做安全测试"
- "测试一下 http://xxx 的 WAF 拦截效果"
- "跑一下 http://xxx 的攻击测试"
- "复测一下 SQL 注入和 XSS 攻击"
- "单独测试 Base64 编码绕过"

### 执行方式

从用户输入中提取目标 URL，作为命令行参数传入。建议同时使用 `--output-json` 保存结果供后续截图使用：

```bash
cd ./scripts && python3 run_skill.py <target_url> --output-json screenshots/events_<timestamp>.json
```

指定测试项复测：

```bash
cd ./scripts && python3 run_skill.py <target_url> --retest "SQL 注入,XSS 攻击"
```

示例：
```bash
cd ./scripts && python3 run_skill.py http://192.168.24.55 --output-json screenshots/events_20260514_153000.json
cd ./scripts && python3 run_skill.py http://192.168.24.55:8080/
cd ./scripts && python3 run_skill.py http://192.168.24.55 --retest "Base64 编码绕过,URL 编码绕过"
```

### 预期输出

```
目标站点: http://192.168.24.55/
=================================================================
测试用例             结果         event_id
-----------------------------------------------------------------
SQL 注入             ✅ 拦截       09bac712b4d045bd84983c658a5d4d8a
XSS 攻击             ✅ 拦截       e44337564fe140d0bfe548b43d764313
文件包含             ✅ 拦截       5543f673f36c4f818d375f7b095dde18
CSRF 攻击            ❌ 未拦截     -
...
=================================================================
共 23 项  |  拦截: 18  |  未拦截: 4  |  异常: 1
```

---

## Phase 2: 日志截图（测试完成后可选）

### 触发时机

攻击测试完成后，用户说以下内容时：
- "帮我截图"
- "截一下 WAF 日志"
- "对拦截的事件截图"
- "去 WAF 面板截图"

### 执行流程

1. 如果攻击测试未使用 `--output-json`，先重新执行测试并保存 JSON：`python3 run_skill.py <url> --output-json screenshots/events_<timestamp>.json`
2. 向用户询问 WAF 面板信息：**WAF 地址、用户名、密码**
3. 执行截图脚本

### 执行方式

```bash
cd ./scripts && python3 screenshot_skill.py \
    --waf-url "<WAF面板地址>" \
    --username "<用户名>" \
    --password "<密码>" \
    --events-file screenshots/events_<timestamp>.json
```

参数说明：
- `--waf-url`: WAF 面板地址，如 `https://192.168.24.55:9443`
- `--username`: WAF 登录用户名
- `--password`: WAF 登录密码
- `--events-file`: Phase 1 输出的 JSON 文件路径
- `--headed`: 可选，使用有头浏览器调试
- `--output-dir`: 可选，自定义截图输出目录

截图完成后，**询问用户是否需要生成测试报告**。

### 预期输出

```
共 18 项拦截事件需要截图
登录成功
正在截图 Event ID abc... (SQL 注入): https://192.168.24.55:9443/log/detect_log/detail?event_id=abc...
  截图成功: sql_event_abc..._detail_20260514_153000.png (1.2 MB)
...
截图完成: 成功 17 / 失败 1 / 总计 18
截图目录: /path/to/scripts/screenshots/session_20260514_153000
```

---

## Phase 3: 报告生成（截图完成后可选）

### 触发时机

截图完成后，用户说以下内容时：
- "生成报告"
- "出一份测试报告"
- "生成 Word 报告"

### 执行方式

```bash
cd ./scripts && python3 report_skill.py \
    --screenshots-dir screenshots/session_<timestamp>
```

参数说明：
- `--screenshots-dir`: 截图所在的目录（screenshot_skill.py 输出的目录）
- `--template-path`: 可选，自定义 Word 模板路径（默认使用技能目录 `doc/H20-单机反代测试方案v1.2.docx`）
- `--output-path`: 可选，自定义输出路径（默认保存到截图目录下）

### 预期输出

```
找到 17 张详情截图
截图分类:
  SQL注入攻击: 1 张
  XSS攻击: 1 张
  ...
表格匹配:
  表格 1 -> SQL注入攻击 (有截图)
  表格 2 -> XSS攻击 (有截图)
  ...
报告已生成: /path/to/screenshots/session_xxx/测试报告_20260514_153000.docx
共插入 15 张截图到 15 个表格
```

---

## 注意事项

- 测试脚本目录：`waf-security-test/scripts/`，入口文件：`run_skill.py`
- 所有攻击用例在 `waf-security-test/scripts/attack/` 目录下
- 截图脚本：`screenshot_skill.py`，报告脚本：`report_skill.py`
- 依赖：`pip install requests playwright python-docx`
- Playwright 浏览器安装：`playwright install chromium`
- 截图功能使用 Playwright（非 Selenium），无需 ChromeDriver
- 测试请求会产生真实的拦截日志，event_id 可直接用于 waf-whitelist skill 进行加白
- 报告模板路径：`waf-security-test/doc/H20-单机反代测试方案v1.2.docx`（已内置到技能目录，无需额外配置）
