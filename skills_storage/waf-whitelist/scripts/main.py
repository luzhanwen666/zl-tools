import os
import re
import requests
import urllib3
from typing import Optional
from urllib.parse import urlparse
from requests.exceptions import ConnectionError, Timeout, RequestException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 配置（从环境变量读取）─────────────────────────────
BASE_URL  = os.environ.get("BASE_URL", "")
API_TOKEN = os.environ.get("API_TOKEN", "")
TIMEOUT   = 10
# ──────────────────────────────────────────────────────

def _check_env():
    """检查必要环境变量，缺失时输出明确提示"""
    missing = []
    if not BASE_URL:
        missing.append("BASE_URL")
    if not API_TOKEN:
        missing.append("API_TOKEN")
    if missing:
        print(f"[配置缺失] 以下环境变量未设置: {', '.join(missing)}")
        print("请告知 AI 你的配置信息，AI 将帮你写入环境变量。")
        print("示例：BASE_URL=https://192.168.x.x:9443  API_TOKEN=your-token")
        return False
    return True


def get_headers():
    return {
        "API-TOKEN":    API_TOKEN,
        "Content-Type": "application/json",
        "Referer":      BASE_URL,
    }


# ── 日志查询 ───────────────────────────────────────────

def fetch_log_detail(event_id: str, timestamp: Optional[str] = None) -> Optional[dict]:
    """查询日志详情，返回单条日志 dict，失败返回 None"""
    if not event_id:
        print("参数错误: event_id 不能为空")
        return None

    params = {
        "scope":           "log:detect_log:detail",
        "event_id__exact": event_id,
    }
    if timestamp:
        params["timestamp__exact"] = timestamp

    try:
        resp = requests.get(
            f"{BASE_URL}/api/FilterV2API",
            headers=get_headers(), params=params,
            timeout=TIMEOUT, verify=False
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[DEBUG] 接口原始响应: {data}")

        if data.get("err"):
            print(f"接口返回错误: {data['err']}")
            return None

        logs = data.get("data", [])
        if not logs:
            print("未查询到相关日志")
            return None

        return logs[0]

    except ConnectionError:
        print(f"连接失败，请检查网络: {BASE_URL}")
    except Timeout:
        print(f"请求超时（超过 {TIMEOUT} 秒）")
    except requests.exceptions.HTTPError as e:
        _handle_http_error(e)
    except requests.exceptions.JSONDecodeError:
        print("响应解析失败，返回内容不是合法 JSON")
    except RequestException as e:
        print(f"请求异常: {e}")

    return None


def print_log(log: dict):
    """格式化输出日志详情"""
    req_header = log.get("req_header", "").strip()
    print("=" * 60)
    print("【攻击事件详情】")
    print("=" * 60)
    print(f"  事件 ID        : {log.get('event_id')}")
    print(f"  攻击类型       : {log.get('attack_type')}")
    print(f"  风险等级       : {log.get('risk_level')}（{log.get('risk_level_num')}级）")
    print(f"  处置动作       : {log.get('action', {}).get('translation')}")
    print(f"  检测原因       : {log.get('reason')}")
    print(f"  攻击载荷       : {log.get('payload')}")
    print(f"  载荷位置       : {log.get('location')}")
    print("-" * 60)
    print("【网络信息】")
    print(f"  源 IP          : {log.get('src_ip')}:{log.get('src_port')}")
    print(f"  目标 IP        : {log.get('dst_ip')}:{log.get('dst_port')}")
    print(f"  协议           : {log.get('scheme', '').upper()}")
    print(f"  请求方法       : {log.get('method')}")
    print(f"  访问 URL       : {log.get('website')}")
    print(f"  URL 路径       : {log.get('url_path')}")
    print(f"  状态码         : {log.get('status_code') or '无'}")
    print("-" * 60)
    print("【防护策略】")
    print(f"  站点名称       : {log.get('website_name')}")
    print(f"  策略组名称     : {log.get('req_policy_group_name')}")
    print(f"  规则 ID        : {log.get('rule_id')}")
    print(f"  检测模块       : {log.get('module')}")
    print(f"  检测耗时       : {log.get('req_detect_time')} ms")
    print("-" * 60)
    print("【原始请求头】")
    print(req_header)
    print("=" * 60)


# ── 站点查询 ───────────────────────────────────────────

def fetch_site_id(website_name: str) -> Optional[int]:
    """根据站点名称查询站点 ID"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/FilterV2API",
            headers=get_headers(),
            params={"scope": "detect:asset:site:all"},
            timeout=TIMEOUT, verify=False
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("err"):
            print(f"站点查询失败: {data['err']}")
            return None

        for site in data.get("data", []):
            if site.get("name") == website_name:
                return int(site["id"])

        print(f"未找到站点名称匹配: {website_name}")
        return None

    except Exception as e:
        print(f"站点查询异常: {e}")
        return None




def build_uri_regex(url_path: str) -> str:
    """提取纯路径，生成精确 URI 正则（允许 query string，不匹配其他路径）"""
    path = urlparse(url_path).path or "/"
    return f"^{re.escape(path)}(\\?.*)?$"


def add_whitelist(log: dict, comment: Optional[str] = None, is_global: bool = False) -> Optional[dict]:
    """根据日志字段构建并提交加白规则"""
    method       = log.get("method", "GET")
    host         = log.get("host", "")
    url_path     = log.get("url_path", "/")
    event_id     = log.get("event_id", "")
    website_name = log.get("website_name", "")
    risk_level   = log.get("req_risk_level_num") or log.get("risk_level_num", 3)
    uri_regex    = build_uri_regex(url_path)

    # 判断规则类型：内置规则 or 检测模块
    req_rule_module     = log.get("req_rule_module", "")
    req_skynet_rule_ids = log.get("req_skynet_rule_id_list") or []
    is_skynet_rule      = req_rule_module == "m_rule" and len(req_skynet_rule_ids) > 0

    if is_skynet_rule:
        action     = "modify_skynet_rule"
        api_path   = "/api/ModifySkynetRulePolicyRuleAPI"
        rule_ids   = list({str(rid) for rid in req_skynet_rule_ids})
        action_payload = {"skynet_rule_management": {"disabled": rule_ids, "enabled": []}}
        print(f"  规则类型: 内置规则  skynet_rule_ids={rule_ids}")
    else:
        action     = "modify_module"
        api_path   = "/api/ModifyModulePolicyRuleAPI"
        module     = log.get("req_module") or log.get("module", "")
        action_payload = {"module_management": {"disabled": [module], "enabled": []}}
        print(f"  规则类型: 检测模块  module={module}")

    # 加白范围：绑定站点 or 全局
    if is_global:
        websites   = []
        scope_flag = True
        print(f"  加白范围: 全局")
    else:
        site_id = fetch_site_id(website_name)
        if site_id is None:
            print(f"  无法获取站点 ID，降级为全局加白")
            websites   = []
            scope_flag = True
        else:
            websites   = [site_id]
            scope_flag = False
            print(f"  加白范围: 绑定站点 [{site_id}]（{website_name}）")

    rule_comment = comment if comment else f"消除误报 - {event_id}"
    print(f"  策略名称: {rule_comment}")
    print(f"  生成 URI 正则: {uri_regex}")

    payload = {
        "attack_type": None,
        "comment": rule_comment,
        "create_time": 0, "expire_time": 0, "id": 0,
        "action": action,
        "forbidden_page_config": None,
        "log_option": "Persistence",
        "is_enabled": True, "is_expired": False, "is_global": scope_flag,
        "last_update_time": 0,
        "pattern": {
            "$AND": [
                {"str": {"method": method},    "decode_methods": []},
                {"str": {"host": host},         "decode_methods": []},
                {"re":  {"urlpath": uri_regex}, "decode_methods": []},
            ]
        },
        "websites": websites,
        "risk_level": risk_level,
        "delay": 0, "percentage": 100,
        "cron_config": {
            "type": "all", "start": "00:00", "end": "23:59",
            "days": [], "start_timestamp": 0, "end_timestamp": 0
        },
        "req_rule_id": "", "rsp_rule_id": "", "duration": 1,
        "forward_address": {"host": "", "port": 80, "protocol": "http"},
        "session_method": {"param": "", "type": "src_ip"},
        "mark_flag": "", "priority": 0, "custom_fsl": "",
        "ignore_skip_remaining": False, "hook": 0, "is_protected": False,
        **action_payload,
    }

    try:
        import json
        print(f"\n[DEBUG] 发送 payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        resp = requests.post(
            f"{BASE_URL}{api_path}",
            headers=get_headers(), json=payload,
            timeout=TIMEOUT, verify=False
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("err"):
            print(f"加白失败: {result['err']}")
            return None

        print("加白成功")
        return result

    except ConnectionError:
        print(f"连接失败，请检查网络: {BASE_URL}")
    except Timeout:
        print(f"请求超时（超过 {TIMEOUT} 秒）")
    except requests.exceptions.HTTPError as e:
        _handle_http_error(e)
    except requests.exceptions.JSONDecodeError:
        print("响应解析失败，返回内容不是合法 JSON")
    except RequestException as e:
        print(f"请求异常: {e}")

    return None


# ── 公共 ───────────────────────────────────────────────

def _handle_http_error(e: requests.exceptions.HTTPError):
    status = e.response.status_code
    if status == 401:
        print("认证失败，请检查 API-TOKEN")
    elif status == 403:
        print("权限不足")
    elif status == 404:
        print("接口不存在，请确认 URL 是否正确")
    else:
        print(f"请求失败，状态码: {status}，响应: {e.response.text}")


# ── 主流程 ─────────────────────────────────────────────

def run(event_id: str, timestamp: Optional[str] = None, comment: Optional[str] = None, is_global: bool = False):
    # 0. 检查环境变量
    if not _check_env():
        return

    # 1. 查询日志
    print(f"\n正在查询日志 event_id={event_id} ...")
    log = fetch_log_detail(event_id, timestamp)
    if not log:
        return

    # 2. 展示日志详情
    print_log(log)

    # 3. 二次确认
    confirm = input("\n是否对该事件进行加白？(y/n): ").strip().lower()
    if confirm != "y":
        print("已取消加白")
        return

    # 4. 执行加白
    print("\n正在提交加白规则...")
    add_whitelist(log, comment=comment, is_global=is_global)


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="WAF 误报加白工具")
    parser.add_argument("event_id", help="拦截事件的 event_id")
    parser.add_argument("--comment", help="自定义策略名称，不传则默认为 '消除误报 - <event_id>'", default=None)
    parser.add_argument("--global", dest="is_global", action="store_true", help="全局加白，不绑定站点")
    args = parser.parse_args()

    run(args.event_id, comment=args.comment, is_global=args.is_global)
