"""
WAF 样本发包测试 - 供 skill 调用
用法: python3 run_sample_test.py <target_url> [--sample-dir <目录>] [--threads <线程数>] [--timeout <秒>] [--intercept-codes <状态码>]
"""
import os
import sys
import re
import time
import socket
import ssl
import json
import zipfile
import tarfile
import argparse
import warnings
import urllib.request
import urllib.error
import openpyxl
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

warnings.filterwarnings("ignore")

DEFAULT_SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "混合黑白样本")
DEFAULT_INTERCEPT_CODES = {403, 406, 444}
DEFAULT_THREADS = 10
DEFAULT_TIMEOUT = 10

# 从环境变量读取 WAF 配置
ENV_WAF_URL   = os.environ.get("BASE_URL", "")
ENV_API_TOKEN = os.environ.get("API_TOKEN", "")


def check_waf_env():
    """检查 WAF 环境变量，缺失时输出提示"""
    missing = []
    if not ENV_WAF_URL:
        missing.append("BASE_URL")
    if not ENV_API_TOKEN:
        missing.append("API_TOKEN")
    if missing:
        print(f"[配置缺失] 以下环境变量未设置: {', '.join(missing)}")
        print("请告知 AI 你的 WAF 地址和 API Token，AI 将帮你写入环境变量。")
        return False
    return True


def extract_samples(archive_path: str, extract_to: str) -> str:
    """
    使用 Python 内置库解压样本压缩包，支持 .zip / .tar.gz / .tar.bz2 / .tar
    返回解压后的目录路径
    """
    archive_path = os.path.abspath(archive_path)
    extract_to = os.path.abspath(extract_to)
    os.makedirs(extract_to, exist_ok=True)

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_to)
        print(f"[解压] zip 格式解压完成 → {extract_to}")
    elif tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(extract_to)
        print(f"[解压] tar 格式解压完成 → {extract_to}")
    else:
        print(f"[错误] 不支持的压缩格式: {archive_path}")
        sys.exit(1)

    return extract_to


def load_samples(sample_dir: str):
    """递归加载 .black 和 .white 样本文件，自动处理嵌套子目录"""
    samples = []
    sample_dir = os.path.abspath(sample_dir)

    if not os.path.isdir(sample_dir):
        print(f"[错误] 样本目录不存在: {sample_dir}")
        sys.exit(1)

    for root, dirs, files in os.walk(sample_dir):
        # 跳过以 __ 开头的目录（如 __MACOSX）
        dirs[:] = [d for d in dirs if not d.startswith("__")]
        for fname in files:
            # 跳过以 __ 开头的文件
            if fname.startswith("__"):
                continue
            if fname.endswith(".black"):
                sample_type = "black"
            elif fname.endswith(".white"):
                sample_type = "white"
            else:
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                samples.append({"name": fname, "type": sample_type, "content": content})
            except Exception:
                pass

    return samples


def load_excel_samples(excel_path: str, column_name: str) -> list:
    """从 Excel 文件中读取指定列的 HTTP 请求载荷，全部视为黑样本，自动关联用例名称"""
    if not os.path.isfile(excel_path):
        print(f"[错误] Excel 文件不存在: {excel_path}")
        sys.exit(1)

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    header_row = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))

    # 查找载荷列
    col_idx = None
    for i, val in enumerate(header_row, start=1):
        if val and str(val).strip() == column_name:
            col_idx = i
            break

    if col_idx is None:
        available = [str(v).strip() for v in header_row if v]
        print(f"[错误] 未找到列 '{column_name}'")
        print(f"  可用列名: {', '.join(available)}")
        wb.close()
        sys.exit(1)

    # 自动查找用例名称列（精确匹配优先）
    name_col_idx = None
    name_col_keywords = ["用例名称", "name", "case", "名称"]
    for kw in name_col_keywords:
        for i, val in enumerate(header_row, start=1):
            if val and str(val).strip() == kw:
                name_col_idx = i
                break
        if name_col_idx:
            break

    samples = []
    row_num = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_num += 1
        cell_value = row[col_idx - 1]
        if not cell_value or not str(cell_value).strip():
            continue

        content = str(cell_value).strip()
        if not re.match(r"^(GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH|CONNECT|TRACE)\b", content, re.IGNORECASE):
            print(f"  [跳过] 第 {row_num + 1} 行: 不以 HTTP 方法开头")
            continue

        name = f"excel_row_{row_num + 1}.black"
        case_name = ""
        if name_col_idx and name_col_idx <= len(row):
            raw = row[name_col_idx - 1]
            if raw:
                case_name = str(raw).strip()

        samples.append({"name": name, "type": "black", "content": content, "case_name": case_name})

    wb.close()

    if not samples:
        print(f"[错误] Excel 列 '{column_name}' 中未找到有效的 HTTP 请求载荷")
        sys.exit(1)

    print(f"[Excel] 从 '{column_name}' 列读取到 {len(samples)} 条载荷" +
          (f"，已关联 '{header_row[name_col_idx - 1]}' 列" if name_col_idx else ""))
    return samples


def load_samples_from_json(json_path: str, sample_names: list) -> list:
    """从上次测试的 JSON 结果文件中加载指定样本用于复测"""
    if not os.path.isfile(json_path):
        print(f"[错误] JSON 结果文件不存在: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        all_results = json.load(f)

    result_map = {r["name"]: r for r in all_results}
    samples = []
    not_found = []
    for name in sample_names:
        if name in result_map:
            r = result_map[name]
            samples.append({"name": r["name"], "type": r["type"], "content": r["content"]})
        else:
            not_found.append(name)

    if not_found:
        print(f"[警告] 以下样本在 JSON 结果中未找到: {', '.join(not_found)}")

    if not samples:
        print("[错误] 未匹配到任何有效样本")
        sys.exit(1)

    return samples


def send_raw_http(target_url: str, raw_request: str, timeout: int) -> tuple:
    """
    将样本中的 Host 替换为目标 host，发送原始 HTTP 请求，返回 (status_code, response_time_ms)
    """
    parsed = urlparse(target_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    use_ssl = parsed.scheme == "https"

    # 替换 Host 头
    raw = re.sub(r"(?i)^Host:.*$", f"Host: {parsed.netloc}", raw_request, flags=re.MULTILINE)

    # 确保请求行路径正确（保留原始路径，只替换 Host）
    raw_bytes = raw.encode("utf-8", errors="replace")

    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        if use_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=host)

        sock.sendall(raw_bytes)

        # 读取完整响应（含 body），用于提取 event_id
        response = b""
        sock.settimeout(timeout)
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if len(response) > 65536:
                break

        sock.close()
        elapsed = int((time.time() - start) * 1000)

        # 解析状态码和响应头
        first_line = response.split(b"\r\n")[0].decode("utf-8", errors="ignore")
        match = re.match(r"HTTP/\S+\s+(\d+)", first_line)
        status_code = int(match.group(1)) if match else 0

        # 解析响应头，提取 event_id
        header_end = response.find(b"\r\n\r\n")
        headers_raw = response[:header_end].decode("utf-8", errors="ignore") if header_end >= 0 else response.decode("utf-8", errors="ignore")
        event_id = ""
        for line in headers_raw.split("\r\n")[1:]:
            if ":" in line:
                key, val = line.split(":", 1)
                key_lower = key.strip().lower()
                if key_lower in ("x-event-id", "event_id", "x-chaitin-event-id", "x-waf-event-id"):
                    event_id = val.strip()

        # 从响应 body 的 HTML 注释中提取 event_id
        if not event_id and header_end >= 0:
            body = response[header_end + 4:].decode("utf-8", errors="ignore")
            m = re.search(r"event_id[:\s]+([a-f0-9]+)", body, re.IGNORECASE)
            if m:
                event_id = m.group(1)

        return status_code, elapsed, event_id

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        return 0, elapsed, ""


def parse_http_request(raw: str) -> dict:
    """从原始 HTTP 请求报文中提取 method、host、urlpath"""
    lines = raw.strip().splitlines()
    method, urlpath, host = "GET", "/", ""

    # 解析请求行
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2:
            method = parts[0].upper()
            full_path = parts[1]
            # 只取路径部分，去掉 query string
            urlpath = urlparse(full_path).path or "/"

    # 解析 Host 头
    for line in lines[1:]:
        if line.lower().startswith("host:"):
            host = line.split(":", 1)[1].strip()
            break

    return {"method": method, "host": host, "urlpath": urlpath}


def create_block_rule(waf_url: str, api_token: str, sample_name: str, method: str, host: str, urlpath: str) -> bool:
    """调用 PolicyRuleAPI 创建拦截规则，全局放行"""
    api_url = waf_url.rstrip("/") + "/api/PolicyRuleAPI"

    payload = {
        "attack_type": 62,
        "comment": f"样本绕过补规则 - {sample_name}",
        "create_time": 0, "expire_time": 0, "id": 0,
        "action": "deny",
        "forbidden_page_config": None,
        "log_option": "Persistence",
        "is_enabled": True, "is_expired": False, "is_global": True,
        "last_update_time": 0,
        "pattern": {
            "$AND": [
                {"str": {"method": method},   "decode_methods": []},
                {"str": {"host": host},        "decode_methods": []},
                {"re":  {"urlpath": urlpath},  "decode_methods": []},
            ]
        },
        "websites": [], "modules_list": [],
        "module_management": {"disabled": [], "enabled": []},
        "risk_level": 3, "delay": 0, "percentage": 100,
        "cron_config": {"type": "all", "start": "00:00", "end": "23:59",
                        "days": [], "start_timestamp": 0, "end_timestamp": 0},
        "req_rule_id": "", "rsp_rule_id": "", "duration": 1,
        "forward_address": None,
        "session_method": {"param": "", "type": "src_ip"},
        "mark_flag": "", "priority": 0, "custom_fsl": "",
        "ignore_skip_remaining": False, "hook": 0, "is_protected": False
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "API-TOKEN": api_token,
                "Referer": waf_url,
            }
        )
        # 跳过 SSL 验证
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("err"):
                print(f"  [规则创建失败] {sample_name}: {result['err']}")
                return False
            rule_id = result.get("data", {}).get("id", "?")
            print(f"  [规则创建成功] {sample_name} → 规则ID: {rule_id}  {method} {host}{urlpath}")
            return True

    except Exception as e:
        print(f"  [规则创建异常] {sample_name}: {e}")
        return False



def run_test(sample: dict, target_url: str, intercept_codes: set, timeout: int) -> dict:
    status_code, elapsed, event_id = send_raw_http(target_url, sample["content"], timeout)
    blocked = status_code in intercept_codes
    sample_type = sample["type"]

    if sample_type == "black":
        result = "黑样本拦截" if blocked else "黑样本绕过"
        expected = blocked
    else:
        result = "白样本拦截" if blocked else "白样本通过"
        expected = not blocked

    return {
        "name":      sample["name"],
        "case_name": sample.get("case_name", ""),
        "type":      sample_type,
        "status":    status_code,
        "blocked":   blocked,
        "result":    result,
        "expected":  expected,
        "elapsed":   elapsed,
        "event_id":  event_id,
        "content":   sample["content"],
    }


def run_all(target_url: str, sample_dir: str, threads: int, timeout: int, intercept_codes: set,
            waf_url: str = None, api_token: str = None, auto_block: bool = False,
            retest_bypass: bool = False, samples: list = None):
    if samples is None:
        samples = load_samples(sample_dir)
    if not samples:
        print("[错误] 未找到任何 .black 或 .white 样本文件")
        sys.exit(1)

    # 复测模式：只跑黑样本
    if retest_bypass:
        samples = [s for s in samples if s["type"] == "black"]
        if not samples:
            print("[错误] 未找到任何 .black 黑样本文件")
            sys.exit(1)
        print(f"\n[复测模式] 仅对 {len(samples)} 条黑样本进行拦截复测")

    white_total = sum(1 for s in samples if s["type"] == "white")
    black_total = sum(1 for s in samples if s["type"] == "black")

    print(f"\n目标站点  : {target_url}")
    print(f"样本来源  : {os.path.abspath(sample_dir) if sample_dir else '(内存加载)'}")
    print(f"样本总数  : {len(samples)}  (白样本: {white_total}, 黑样本: {black_total})")
    print(f"线程数    : {threads}  超时: {timeout}s  拦截状态码: {sorted(intercept_codes)}")
    print("=" * 70)

    stats = {"white_pass": 0, "white_block": 0, "black_block": 0, "black_pass": 0}
    response_times = []
    bypass_list = []
    false_positive_list = []
    results_list = []
    completed = 0

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(run_test, s, target_url, intercept_codes, timeout): s for s in samples}
        for future in as_completed(futures):
            r = future.result()
            completed += 1
            results_list.append(r)
            response_times.append(r["elapsed"])

            if r["type"] == "black":
                if r["blocked"]:
                    stats["black_block"] += 1
                else:
                    stats["black_pass"] += 1
                    bypass_list.append((r["name"], r.get("content", "")))
            else:
                if r["blocked"]:
                    stats["white_block"] += 1
                    false_positive_list.append(r["name"])
                else:
                    stats["white_pass"] += 1

            # 进度输出
            symbol = "✅" if r["expected"] else "❌"
            print(f"  {symbol} [{completed:>4}/{len(samples)}] {r['result']:<10} {r['status']:>3}  {r['elapsed']:>5}ms  {r['name']}")

    # 统计
    avg_time = int(sum(response_times) / len(response_times)) if response_times else 0
    intercept_rate = round(stats["black_block"] / black_total * 100, 1) if black_total else 0
    false_positive_rate = round(stats["white_block"] / white_total * 100, 1) if white_total else 0

    print("\n" + "=" * 70)
    print("【测试结果统计】")
    print(f"  白样本通过  : {stats['white_pass']}")
    print(f"  白样本拦截  : {stats['white_block']}  (误报率: {false_positive_rate}%)")
    print(f"  黑样本拦截  : {stats['black_block']}  (拦截率: {intercept_rate}%)")
    print(f"  黑样本绕过  : {stats['black_pass']}")
    print(f"  平均响应时间: {avg_time} ms")
    print("=" * 70)

    if bypass_list:
        print(f"\n【黑样本绕过列表】({len(bypass_list)} 条)")
        for name, _ in bypass_list:
            print(f"  - {name}")

        # 自动创建拦截规则
        if auto_block and waf_url and api_token:
            print(f"\n【自动创建拦截规则】")
            parsed_target = urlparse(target_url)
            target_host = parsed_target.netloc
            ok, fail = 0, 0
            for name, content in bypass_list:
                info = parse_http_request(content)
                host = target_host
                success = create_block_rule(waf_url, api_token, name, info["method"], host, info["urlpath"])
                if success:
                    ok += 1
                else:
                    fail += 1
            print(f"  规则创建完成：成功 {ok} 条，失败 {fail} 条")

    if false_positive_list:
        print(f"\n【白样本误报列表】({len(false_positive_list)} 条)")
        for name in false_positive_list:
            print(f"  - {name}")

    return results_list


def save_results_json(results: list, output_path: str):
    """将测试结果保存为 JSON 文件"""
    output = []
    for r in results:
        output.append({
            "name": r["name"], "case_name": r.get("case_name", ""),
            "type": r["type"], "status": r["status"],
            "blocked": r["blocked"], "result": r["result"], "elapsed": r["elapsed"],
            "event_id": r.get("event_id", ""),
            "content": r["content"],
        })

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[结果已保存] {output_path}  ({len(output)} 条记录)")


def save_results_excel(results: list, output_path: str, target_url: str):
    """将测试结果保存为格式化 Excel 报告"""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    blocked_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    bypass_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    wb = openpyxl.Workbook()

    # --- Sheet 1: 测试结果明细 ---
    ws = wb.active
    ws.title = "测试结果明细"

    headers = ["序号", "样本名称", "样本类型", "状态码", "响应时间(ms)", "测试结果", "event_id"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    for i, r in enumerate(results, 1):
        display_name = r.get("case_name", "") or r["name"]
        row_vals = [
            i, display_name, r["type"], r["status"], r["elapsed"], r["result"],
            r.get("event_id", ""),
        ]
        fill = blocked_fill if r["blocked"] else bypass_fill
        for col, val in enumerate(row_vals, 1):
            cell = ws.cell(row=i + 1, column=col, value=val)
            cell.alignment = center_align
            cell.border = thin_border
            cell.fill = fill

    widths = [8, 30, 12, 10, 14, 14, 36]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    # --- Sheet 2: 测试汇总 ---
    ws2 = wb.create_sheet("测试汇总")

    black_total = sum(1 for r in results if r["type"] == "black")
    white_total = sum(1 for r in results if r["type"] == "white")
    black_blocked = sum(1 for r in results if r["type"] == "black" and r["blocked"])
    black_bypass = sum(1 for r in results if r["type"] == "black" and not r["blocked"])
    white_blocked = sum(1 for r in results if r["type"] == "white" and r["blocked"])
    white_passed = sum(1 for r in results if r["type"] == "white" and not r["blocked"])
    intercept_rate = f"{black_blocked / black_total * 100:.1f}%" if black_total else "0%"
    fp_rate = f"{white_blocked / white_total * 100:.1f}%" if white_total else "0%"
    avg_time = int(sum(r["elapsed"] for r in results) / len(results)) if results else 0

    summary = [
        ["WAF 样本测试报告"],
        [""],
        ["目标站点", target_url],
        ["样本总数", len(results)],
        ["黑样本拦截", black_blocked, f"(拦截率: {intercept_rate})"],
        ["黑样本绕过", black_bypass],
        ["白样本通过", white_passed],
        ["白样本拦截", white_blocked, f"(误报率: {fp_rate})"],
        ["平均响应时间", f"{avg_time} ms"],
        [""],
        ["颜色说明", ""],
        ["绿色行 = 已拦截", ""],
        ["红色行 = 绕过/误报", ""],
    ]
    for r, row_data in enumerate(summary, 1):
        for c, val in enumerate(row_data, 1):
            cell = ws2.cell(row=r, column=c, value=val)
            cell.border = thin_border
            if r == 1:
                cell.font = Font(bold=True, size=16)
            elif c == 1 and r >= 3 and r <= 9:
                cell.font = Font(bold=True)

    ws2.column_dimensions["A"].width = 18
    ws2.column_dimensions["B"].width = 22
    ws2.column_dimensions["C"].width = 20

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb.save(output_path)
    print(f"\n[Excel 报告已保存] {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WAF 样本发包测试工具")
    parser.add_argument("target_url", help="目标站点 URL，如 http://192.168.24.55")
    parser.add_argument("--archive", default=None, help="样本压缩包路径（zip/tar.gz），指定后自动解压")
    parser.add_argument("--excel", default=None, help="Excel 文件路径 (.xlsx)，指定后从 Excel 读取样本")
    parser.add_argument("--excel-column", default=None, help="Excel 中包含 HTTP 请求载荷的列名（配合 --excel）")
    parser.add_argument("--sample-dir", default=DEFAULT_SAMPLE_DIR, help="样本目录路径（默认：混合黑白样本/）")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS, help="并发线程数（默认：10）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时秒数（默认：10）")
    parser.add_argument("--intercept-codes", default="403,406,444", help="拦截判定状态码，逗号分隔（默认：403,406,444）")
    parser.add_argument("--waf-url", default=None, help="WAF 管理地址，如 https://192.168.24.55:9443")
    parser.add_argument("--api-token", default=None, help="WAF API Token，与 --waf-url 配合使用")
    parser.add_argument("--auto-block", action="store_true", help="对绕过的黑样本自动创建 WAF 拦截规则")
    parser.add_argument("--retest-bypass", action="store_true", help="复测模式：只对黑样本发包，验证拦截规则是否生效")
    parser.add_argument("--retest-sample", default=None, help="复测指定样本，逗号分隔的样本名（配合 --input-json）")
    parser.add_argument("--input-json", default=None, help="上次 JSON 结果文件路径（配合 --retest-sample）")
    parser.add_argument("--output-json", default=None, help="将测试结果保存为 JSON 文件路径")
    parser.add_argument("--output-excel", default=None, help="将测试结果保存为格式化 Excel 报告路径")
    args = parser.parse_args()

    # 参数互斥校验
    input_sources = [args.archive, args.excel, args.retest_sample, (args.sample_dir != DEFAULT_SAMPLE_DIR)]
    active_count = sum(1 for s in input_sources if s)
    if active_count > 1:
        parser.error("请只指定一个样本来源: --archive, --excel, --sample-dir, 或 --retest-sample")

    if args.excel and not args.excel_column:
        parser.error("使用 --excel 时必须同时指定 --excel-column")
    if args.retest_sample and not args.input_json:
        parser.error("使用 --retest-sample 时必须同时指定 --input-json")

    intercept_codes = set(int(c.strip()) for c in args.intercept_codes.split(",") if c.strip().isdigit())

    waf_url = args.waf_url or ENV_WAF_URL
    api_token = args.api_token or ENV_API_TOKEN

    if args.auto_block and not (waf_url and api_token):
        check_waf_env()
        sys.exit(1)

    # 根据输入来源加载样本并执行测试
    results = None

    if args.retest_sample:
        sample_names = [n.strip() for n in args.retest_sample.split(",") if n.strip()]
        print(f"\n[复测模式] 对 {len(sample_names)} 条指定样本进行复测")
        results = run_all(
            args.target_url, None, args.threads, args.timeout,
            intercept_codes, samples=load_samples_from_json(args.input_json, sample_names),
            waf_url=waf_url, api_token=api_token, auto_block=args.auto_block, retest_bypass=True,
        )
    elif args.excel:
        excel_samples = load_excel_samples(args.excel, args.excel_column)
        results = run_all(
            args.target_url, args.excel, args.threads, args.timeout,
            intercept_codes, samples=excel_samples,
            waf_url=waf_url, api_token=api_token, auto_block=args.auto_block,
            retest_bypass=args.retest_bypass,
        )
    else:
        sample_dir = args.sample_dir
        if args.archive:
            extract_to = os.path.join(os.path.dirname(__file__), "samples")
            sample_dir = extract_samples(args.archive, extract_to)
        results = run_all(
            args.target_url, sample_dir, args.threads, args.timeout,
            intercept_codes,
            waf_url=waf_url, api_token=api_token, auto_block=args.auto_block,
            retest_bypass=args.retest_bypass,
        )

    if args.output_json and results:
        save_results_json(results, args.output_json)

    if args.output_excel and results:
        save_results_excel(results, args.output_excel, args.target_url)
