"""
WAF 日志截图脚本 - 使用 Playwright 自动登录 WAF 面板并截取 event 详情页
用法: python3 screenshot_skill.py --waf-url <url> --username <user> --password <pass> --events-file <json>
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime


# run_skill.py 中文测试名 -> 英文文件名前缀（与 report_views.py file_keywords 匹配）
NAME_TO_KEYWORD = {
    "SQL 注入":        "sql",
    "XSS 攻击":        "xss",
    "Java 反序列化":   "java",
    "文件上传":        "fileupload",
    "文件包含":        "fileinclude",
    "PHP 代码注入":    "php",
    "CSRF 攻击":       "csrf",
    "SSRF 攻击":       "ssrf",
    "PHP 反序列化":    "php_deserialization",
    "ASP 攻击":        "asp",
    "Java 代码注入":   "java_code",
    "命令注入":        "code",
    "情报模块":        "intelligence_module",
    "服务器响应":      "server",
    "机器人检测":      "robot",
    "Base64 编码绕过": "base64",
    "URL 编码绕过":    "url",
    "JSON 解析攻击":   "json",
    "16 进制编码":     "onesix",
    "反斜杠转义":      "backslash",
    "XML 编码":        "xml",
    "UTF-7 编码":      "utf7",
    "多层编码解析":    "more_value",
}


def login_waf(page, waf_url, username, password):
    """登录 WAF 面板，返回 True 表示成功"""
    login_url = f"{waf_url.rstrip('/')}/login"
    print(f"正在访问登录页面: {login_url}")
    page.goto(login_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(3000)

    # 用 JS 直接设置值并触发事件（绕过可能的框架遮挡问题）
    page.evaluate('''(creds) => {
        const u = document.querySelector('input#username');
        const p = document.querySelector('input#password');
        if (u) {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(u, creds.username);
            u.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (p) {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(p, creds.password);
            p.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }''', {'username': username, 'password': password})

    page.wait_for_timeout(500)

    # 点击第一个可见的 submit_btn
    buttons = page.locator('button#submit_btn').all()
    clicked = False
    for btn in buttons:
        if btn.is_visible():
            btn.click()
            clicked = True
            break
    if not clicked:
        # fallback: 用 JS 点击
        page.evaluate("document.querySelectorAll('button#submit_btn').forEach(b => { if(b.offsetParent !== null) b.click(); })")

    page.wait_for_timeout(5000)

    # 验证登录成功
    current_url = page.url.lower()
    page_content = page.content().lower()
    success_indicators = [
        '/dashboard' in current_url,
        '/main' in current_url,
        '/home' in current_url,
        'logout' in page_content,
        '退出' in page_content,
        '注销' in page_content,
    ]
    if not any(success_indicators):
        raise Exception("WAF 登录失败，请检查用户名和密码")

    print("登录成功")
    return True


def take_screenshot(page, waf_url, event_id, keyword, test_name, timestamp, output_dir, username, password):
    """访问 event 详情页，先截基本信息，再展开截详情，返回截图信息列表"""
    detail_url = f"{waf_url.rstrip('/')}/log/detect_log/detail?event_id={event_id}"
    print(f"正在截图 Event ID {event_id} ({test_name}): {detail_url}")

    try:
        page.goto(detail_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # 会话过期重定向到登录页
        if '/login' in page.url.lower():
            print(f"  会话过期，重新登录...")
            login_waf(page, waf_url, username, password)
            page.goto(detail_url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

        # 验证页面有效性
        page_title = page.title()
        page_source = page.content()
        is_valid = not any(m in page_title for m in ('404', 'Not Found', '错误', 'Error'))
        is_valid = is_valid and len(page_source) > 1000

        if not is_valid:
            return [{"event_id": event_id, "keyword": keyword, "test_name": test_name, "success": False,
                     "error": f"页面无效: {page_title}"}]

        results = []

        # === 第一张：基本信息截图（五元组、站点信息、源IP等）===
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        basic_filename = f"{keyword}_event_{event_id}_basic_{timestamp}.png"
        basic_filepath = os.path.join(output_dir, basic_filename)
        page.screenshot(path=basic_filepath, full_page=False)
        file_size = round(os.path.getsize(basic_filepath) / (1024 * 1024), 2)
        results.append({
            "event_id": event_id, "keyword": keyword, "test_name": test_name,
            "success": True, "filename": basic_filename, "path": basic_filepath,
            "size_mb": file_size, "type": "basic"
        })
        print(f"  基本信息截图: {basic_filename} ({file_size} MB)")

        # === 第二张：展开详情截图（请求头、请求体、匹配规则等）===
        try:
            page.wait_for_timeout(1000)
            expand_btn = page.locator('button:has-text("展开")').first
            if expand_btn.is_visible():
                expand_btn.click()
                page.wait_for_timeout(2000)
            decode_btn = page.locator('button:has-text("尝试解码")').first
            if decode_btn.is_visible():
                decode_btn.click()
                page.wait_for_timeout(2000)
            for _ in range(3):
                extra_expand = page.locator('button:has-text("展开")').first
                if extra_expand.is_visible():
                    extra_expand.click()
                    page.wait_for_timeout(2000)
                else:
                    break
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  展开详情时出错（不影响截图）: {e}")

        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        detail_filename = f"{keyword}_event_{event_id}_detail_{timestamp}.png"
        detail_filepath = os.path.join(output_dir, detail_filename)
        page.screenshot(path=detail_filepath, full_page=True)
        file_size = round(os.path.getsize(detail_filepath) / (1024 * 1024), 2)
        results.append({
            "event_id": event_id, "keyword": keyword, "test_name": test_name,
            "success": True, "filename": detail_filename, "path": detail_filepath,
            "size_mb": file_size, "type": "detail"
        })
        print(f"  详情截图: {detail_filename} ({file_size} MB)")

        return results

    except Exception as e:
        print(f"  截图失败: {e}")
        return [{"event_id": event_id, "keyword": keyword, "test_name": test_name, "success": False,
                 "error": str(e)}]


def run_screenshots(waf_url, username, password, events_file, output_dir=None, headed=False):
    """主入口：读取事件列表，登录 WAF，逐个截图"""
    from playwright.sync_api import sync_playwright

    # 读取事件列表
    with open(events_file, 'r', encoding='utf-8') as f:
        events = json.load(f)

    # 过滤出有拦截 event_id 的事件
    intercepted = [e for e in events if e.get('event_id') and e['event_id'] != '-']
    if not intercepted:
        print("没有需要截图的拦截事件")
        return []

    print(f"\n共 {len(intercepted)} 项拦截事件需要截图")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots', f'session_{timestamp}')
    os.makedirs(output_dir, exist_ok=True)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            login_waf(page, waf_url, username, password)

            for event in intercepted:
                name = event['name']
                keyword = NAME_TO_KEYWORD.get(name, re.sub(r'[<>:"/\\|?*]', '_', name).lower())
                info = take_screenshot(page, waf_url, event['event_id'], keyword, name, timestamp,
                                       output_dir, username, password)
                results.extend(info)  # 每个事件返回2个结果

        finally:
            browser.close()

    # 统计
    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count
    print(f"\n截图完成: 成功 {success_count} / 失败 {fail_count} / 总计 {len(results)}")
    print(f"截图目录: {output_dir}")

    # 写入 manifest
    manifest = {
        "timestamp": timestamp,
        "waf_url": waf_url,
        "screenshots_dir": output_dir,
        "screenshots": results,
        "total": len(results),
        "success_count": success_count,
        "fail_count": fail_count,
    }
    manifest_path = os.path.join(output_dir, 'screenshots_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='WAF 日志截图工具 (Playwright)')
    parser.add_argument('--waf-url', required=True, help='WAF 面板地址，如 https://192.168.24.55:9443')
    parser.add_argument('--username', required=True, help='WAF 登录用户名')
    parser.add_argument('--password', required=True, help='WAF 登录密码')
    parser.add_argument('--events-file', required=True, help='攻击测试输出的 JSON 文件路径')
    parser.add_argument('--output-dir', default=None, help='截图输出目录（默认自动创建）')
    parser.add_argument('--headed', action='store_true', help='使用有头浏览器（调试用）')
    args = parser.parse_args()

    run_screenshots(args.waf_url, args.username, args.password, args.events_file,
                    args.output_dir, args.headed)
