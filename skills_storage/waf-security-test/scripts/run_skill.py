"""
WAF 安全测试入口 - 供 skill 调用
用法: python3 run_skill.py <target_url> [--output-json <path>]
"""
import re
import sys
import os
import json
import argparse
import warnings
warnings.filterwarnings("ignore")

from attack.sql_attack import attack_sql
from attack.xss_attack import attack_xss
from attack.java_attack import attack_java
from attack.fileupload_attack import attack_fileupload
from attack.fileinclude_attack import attack_fileinclude
from attack.php_attack import attack_php
from attack.csrf_attack import attack_csrf
from attack.ssrf_attack import attack_ssrf
from attack.php_deserialization_attack import attack_php_deserialization
from attack.asp_attack import attack_asp
from attack.javacode_attack import attack_javacode
from attack.code_attack import attack_code
from attack.intelligence_module_attack import attack_intelligence_module
from attack.server_attack import attack_server
from attack.robot_attack import attack_robot
from attack.base64_attack import attack_base64
from attack.url_attack import attack_url
from attack.json_attack import attack_json
from attack.onesix_attack import attack_onesix
from attack.backslash_escape_attack import attack_backslash_escape
from attack.xml_attack import attack_xml
from attack.utf7_attack import attack_utf7
from attack.more_attack import attack_more


PATTERN = r'<!--\s*event_id:\s*([a-f0-9]{32})\s*-->'

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
}

# 所有测试用例：(显示名称, 函数, 是否需要 headers)
ATTACK_CASES = [
    ("SQL 注入",        attack_sql,                   True),
    ("XSS 攻击",        attack_xss,                   True),
    ("Java 反序列化",   attack_java,                  True),
    ("文件上传",        attack_fileupload,             True),
    ("文件包含",        attack_fileinclude,            True),
    ("PHP 代码注入",    attack_php,                   True),
    ("CSRF 攻击",       attack_csrf,                  True),
    ("SSRF 攻击",       attack_ssrf,                  True),
    ("PHP 反序列化",    attack_php_deserialization,   True),
    ("ASP 攻击",        attack_asp,                   True),
    ("Java 代码注入",   attack_javacode,              True),
    ("命令注入",        attack_code,                  True),
    ("情报模块",        attack_intelligence_module,   True),
    ("服务器响应",      attack_server,                True),
    ("机器人检测",      attack_robot,                 True),
    ("Base64 编码绕过", attack_base64,                True),
    ("URL 编码绕过",    attack_url,                   True),
    ("JSON 解析攻击",   attack_json,                  True),
    ("16 进制编码",     attack_onesix,                True),
    ("反斜杠转义",      attack_backslash_escape,      True),
    ("XML 编码",        attack_xml,                   True),
    ("UTF-7 编码",      attack_utf7,                  True),
    ("多层编码解析",    attack_more,                  True),
]


def complete_url(url: str) -> str:
    """确保 URL 末尾有 /"""
    url = url.strip()
    if re.match(r'^https?://[^/]+$', url, re.IGNORECASE):
        return url + "/"
    return url


def run_tests(target_url: str, retest_names: list = None):
    url = complete_url(target_url)
    cases = ATTACK_CASES
    if retest_names:
        cases = [(n, f, h) for n, f, h in ATTACK_CASES if n in retest_names]
        if not cases:
            print(f"[错误] 未匹配到任何测试项，可选: {[n for n, _, _ in ATTACK_CASES]}")
            sys.exit(1)

    print(f"\n目标站点: {url}")
    if retest_names:
        print(f"复测项  : {', '.join(retest_names)}")
    print("=" * 65)
    print(f"{'测试用例':<20} {'结果':<10} {'event_id'}")
    print("-" * 65)

    success, fail, error = 0, 0, 0
    results = []

    for name, func, need_headers in cases:
        try:
            if need_headers:
                msg, success, fail, error, event_id = func(
                    url, HEADERS, PATTERN, success, fail, error
                )
            else:
                msg, success, fail, error, event_id = func(
                    url, PATTERN, success, fail, error
                )

            status = "✅ 拦截" if event_id else "❌ 未拦截"
            eid    = event_id if event_id else "-"
            print(f"{name:<20} {status:<12} {eid}")
            results.append({"name": name, "status": status, "event_id": eid, "msg": msg})

        except Exception as e:
            print(f"{name:<20} {'⚠️ 异常':<12} {e}")
            results.append({"name": name, "status": "⚠️ 异常", "event_id": "-", "msg": str(e)})
            error += 1

    print("=" * 65)
    print(f"共 {len(cases)} 项  |  拦截: {success}  |  未拦截: {fail}  |  异常: {error}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='WAF 安全测试')
    parser.add_argument('target_url', help='目标站点 URL')
    parser.add_argument('--output-json', help='将结果保存为 JSON 文件路径')
    parser.add_argument('--retest', help='复测指定测试项，逗号分隔（如 "SQL 注入,XSS 攻击"）')
    args = parser.parse_args()

    if not args.target_url:
        parser.print_help()
        sys.exit(1)

    retest_names = None
    if args.retest:
        retest_names = [n.strip() for n in args.retest.split(",") if n.strip()]

    results = run_tests(args.target_url, retest_names=retest_names)

    if args.output_json:
        out_dir = os.path.dirname(args.output_json)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output_json, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output_json}")
