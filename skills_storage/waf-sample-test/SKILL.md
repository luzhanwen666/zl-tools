---
name: waf-sample-test
description: 对目标站点进行黑白样本发包测试，支持从 ZIP 压缩包或 Excel 表格读取样本，统计拦截率、误报率，支持对绕过样本自动创建 WAF 拦截规则，支持单样本和批量样本复测。
license: MIT
compatibility: opencode
---

## 功能说明

从用户提供的样本来源（ZIP 压缩包、Excel 表格、目录）加载黑白样本，并发发送 HTTP 请求到目标站点，输出：

- 白样本通过 / 白样本拦截（误报）
- 黑样本拦截 / 黑样本绕过
- 拦截率（黑样本拦截比例）
- 误报率（白样本误拦截比例）
- 平均响应时间
- 绕过样本列表 / 误报样本列表

测试完成后，可选择：
1. **自动创建规则** — 对绕过的黑样本自动创建 WAF 拦截规则
2. **保存结果** — 将测试结果保存为 JSON，供后续复测使用
3. **生成 Excel 报告** — 输出格式化 Excel 测试报告（含序号、样本名称、类型、状态码、响应时间、测试结果、event_id）
4. **单样本复测** — 指定某几个样本名重新发请求验证
5. **批量复测** — 对所有绕过的黑样本重新测试

---

## 样本输入方式

### 方式一：ZIP 压缩包（现有）

压缩包中包含 `.black`（黑样本）和 `.white`（白样本）文件，通过文件后缀区分类型。每个文件内容为完整 HTTP 请求报文。

```bash
cd ./scripts && python3 run_sample_test.py <target_url> --archive <压缩包路径>
```

### 方式二：Excel 表格（新增）

用户提供 `.xlsx` 文件，其中某一列包含完整的 HTTP 请求载荷。所有 Excel 载荷均视为黑样本。

**AI 必须询问用户 payload 所在的列名**，若列名不存在脚本会输出可用列名列表。

```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --excel <excel文件路径> \
  --excel-column <列名>
```

示例：
- 用户说 "用这个 Excel 测试 http://192.168.24.55，载荷在「请求报文」列" →
  `python3 run_sample_test.py http://192.168.24.55 --excel /path/to/payloads.xlsx --excel-column 请求报文`

### 方式三：样本目录（现有）

已解压的目录中包含 `.black` / `.white` 文件。

```bash
cd ./scripts && python3 run_sample_test.py <target_url> --sample-dir <目录路径>
```

---

## 触发时机

用户说以下类似内容时使用此 skill：
- "帮我测试一下 http://xxx 的样本检出率"
- "对 http://xxx 跑一下黑白样本测试"
- "用这个 Excel 测试 http://xxx" / "Excel 里的载荷测一下"
- "测试 http://xxx 的拦截率和误报率"
- "发包测试 http://xxx"
- "复测一下 xxx 样本"

---

## Phase 1: 样本测试

### 执行方式

一条命令完成测试，并输出 Excel 报告：

```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --archive <压缩包路径> \
  --output-json screenshots/results_<timestamp>.json \
  --output-excel screenshots/report_<timestamp>.xlsx
```

或使用 Excel 输入：

```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --excel <excel路径> \
  --excel-column <列名> \
  --output-json screenshots/results_<timestamp>.json \
  --output-excel screenshots/report_<timestamp>.xlsx
```

完整参数：
```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --archive <压缩包路径> \
  --threads 10 \
  --timeout 10 \
  --intercept-codes 403,406,444 \
  --output-json screenshots/results.json
```

### 预期输出

```
目标站点  : http://192.168.24.55
样本来源  : /path/to/samples
样本总数  : 500  (白样本: 250, 黑样本: 250)
线程数    : 10  超时: 10s  拦截状态码: [403, 406, 444]
======================================================================
  ✅ [   1/500] 黑样本拦截   403   234ms  0.black
  ✅ [   2/500] 白样本通过   200    89ms  0.white
  ❌ [   3/500] 黑样本绕过   200   156ms  1.black
  ...
======================================================================
【测试结果统计】
  白样本通过  : 245
  白样本拦截  : 5   (误报率: 2.0%)
  黑样本拦截  : 230 (拦截率: 92.0%)
  黑样本绕过  : 20
  平均响应时间: 187 ms
======================================================================

【黑样本绕过列表】(20 条)
  - 1.black
  - 5.black
  ...

[结果已保存] screenshots/results.json  (500 条记录)
[Excel 报告已保存] screenshots/report.xlsx
```

### Excel 报告格式

报告包含两个 Sheet：

**Sheet 1 - 测试结果明细：**

| 序号 | 样本名称 | 样本类型 | 状态码 | 响应时间(ms) | 测试结果 | event_id |
|------|----------|----------|--------|-------------|----------|----------|
| 1 | 0.black | black | 403 | 234 | 黑样本拦截 | evt_xxxxx |
| 2 | 0.white | white | 200 | 89 | 白样本通过 | |
| 3 | 1.black | black | 200 | 156 | 黑样本绕过 | |

- 拦截行：绿色背景
- 绕过/误报行：红色背景

**Sheet 2 - 测试汇总：**

| 项目 | 值 |
|------|-----|
| 目标站点 | http://192.168.24.55 |
| 样本总数 | 500 |
| 黑样本拦截 | 230（拦截率: 92.0%）|
| 黑样本绕过 | 20 |
| 白样本通过 | 245 |
| 白样本拦截 | 5（误报率: 2.0%）|
| 平均响应时间 | 187 ms |

---

## Phase 2: 自动创建拦截规则（可选）

测试完成后，若存在黑样本绕过，可通过 `--auto-block` 参数自动为每条绕过样本在 WAF 上创建拦截规则。

规则匹配条件从样本报文中自动提取：
- Method：请求行中的 HTTP 方法
- Host：样本 Host 头的值
- URI：请求行中的路径部分（去掉 query string）

```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --archive <压缩包路径> \
  --auto-block \
  --waf-url https://192.168.24.55:9443 \
  --api-token <token>
```

WAF 地址和 Token 也可从环境变量 `BASE_URL` / `API_TOKEN` 读取（详见下方环境配置）。

用户触发示例：
- "测试完后帮我把绕过的样本都创建拦截规则"
- "自动补规则"

---

## Phase 3: 样本复测（可选）

### 3a. 单样本/多样本复测（新增）

针对上次测试中的特定样本进行复测，无需重跑全量。**前提：上次测试使用了 `--output-json` 保存了结果。**

AI 应从 JSON 结果中展示所有样本列表，让用户选择要复测的样本名称，然后执行：

```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --retest-sample "excel_row_3.black,excel_row_7.black" \
  --input-json screenshots/results.json
```

用户触发示例：
- "帮我复测一下 excel_row_3.black 这个样本"
- "复测第 5、7、12 条样本"

### 3b. 全部绕过样本批量复测（现有）

对所有黑样本重新发包，验证拦截规则是否生效：

```bash
cd ./scripts && python3 run_sample_test.py <target_url> \
  --sample-dir samples/<解压目录> \
  --retest-bypass
```

用户触发示例：
- "帮我对绕过的样本复测一下"
- "规则创建完了，验证一下是否生效"
- "只跑黑样本"

---

## 环境配置

脚本从系统环境变量读取 WAF 连接信息（用于 `--auto-block` 自动创建规则）：

- `BASE_URL`：WAF 管理地址，如 `https://192.168.24.55:9443`
- `API_TOKEN`：API 认证 Token

### 首次使用 / 环境变量缺失时的处理流程

如果运行脚本后输出 `[配置缺失]`，说明环境变量未设置。
此时需要询问用户：

> "请提供你的 WAF 地址和 API Token，我来帮你写入环境变量。"

用户提供后，执行以下命令将配置永久写入 shell 配置文件：

macOS 操作系统：

```bash
echo 'export BASE_URL="用户提供的地址"' >> ~/.zshrc
echo 'export API_TOKEN="用户提供的Token"' >> ~/.zshrc
source ~/.zshrc
```

CentOS 或 Ubuntu 操作系统：

```bash
echo 'export BASE_URL="用户提供的地址"' >> ~/.bashrc
echo 'export API_TOKEN="用户提供的Token"' >> ~/.bashrc
source ~/.bashrc
```

---

## 典型工作流

```
1. 全量测试（保存结果 + Excel 报告）
   python3 run_sample_test.py http://target --excel payloads.xlsx --excel-column "请求报文" \
     --output-json results.json --output-excel report.xlsx

2. 对绕过样本自动创建规则
   python3 run_sample_test.py http://target --excel payloads.xlsx --excel-column "请求报文" --auto-block

3a. 单样本复测
   python3 run_sample_test.py http://target --retest-sample "excel_row_3.black,excel_row_7.black" --input-json results.json

3b. 全部绕过样本批量复测
   python3 run_sample_test.py http://target --sample-dir samples/xxx --retest-bypass
```

---

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `target_url` | 必填 | 目标站点地址 |
| `--archive` | 无 | 样本压缩包路径，支持 `.zip` / `.tar.gz` / `.tar.bz2` / `.tar` |
| `--excel` | 无 | Excel 文件路径 (.xlsx) |
| `--excel-column` | 无 | Excel 中包含 HTTP 请求载荷的列名（配合 --excel） |
| `--sample-dir` | `混合黑白样本/` | 已解压的样本目录路径 |
| `--threads` | `10` | 并发线程数 |
| `--timeout` | `10` | 请求超时秒数 |
| `--intercept-codes` | `403,406,444` | 判定为拦截的 HTTP 状态码 |
| `--auto-block` | 关闭 | 对绕过黑样本自动创建 WAF 拦截规则 |
| `--retest-bypass` | 关闭 | 复测模式，只对黑样本发包验证规则是否生效 |
| `--retest-sample` | 无 | 复测指定样本，逗号分隔（需配合 --input-json） |
| `--input-json` | 无 | 上次 JSON 结果文件路径（配合 --retest-sample） |
| `--output-json` | 无 | 将测试结果保存为 JSON 文件路径 |
| `--output-excel` | 无 | 将测试结果保存为格式化 Excel 报告路径（含测试结果明细+汇总） |
| `--waf-url` | 无 | WAF 管理地址，与 `--auto-block` 配合使用 |
| `--api-token` | 无 | WAF API Token，与 `--auto-block` 配合使用 |

注意：`--archive`、`--excel`、`--sample-dir`、`--retest-sample` 只能指定一个作为样本来源。

## 样本格式

样本文件为标准 HTTP 请求报文，脚本会自动将 `Host` 头替换为目标站点地址：

```
GET /path?param=value HTTP/1.1
Host: waf-ce.chaitin.cn
User-Agent: Mozilla/5.0 ...
...
```

- `.black` 文件：黑样本，期望被拦截
- `.white` 文件：白样本，期望放行
- Excel 载荷：全部视为黑样本

## 解压约束

- 必须使用 Python 内置模块解压（`zipfile` / `tarfile`），严禁调用系统命令
- 解压目标目录为 `waf-sample-test/scripts/samples/`
- 支持格式：`.zip`、`.tar.gz`、`.tar.bz2`、`.tar`
- 解压后文件名以 `__` 开头的文件不纳入测试样本，自动跳过
- 样本文件支持嵌套在子目录中，脚本会递归扫描所有子目录

## 注意事项

- 脚本通过原始 TCP socket 发送 HTTP 请求，无需 requests 库
- HTTPS 目标自动跳过证书验证
- 依赖：Python 3.9+ 标准库 + openpyxl（`pip install openpyxl`）
