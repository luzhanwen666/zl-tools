import re
import requests
import urllib3
from urllib.parse import urlparse
from requests.exceptions import ConnectionError, Timeout, RequestException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://192.168.24.55:9443"
API_TOKEN = "your-api-token-here"
TIMEOUT = 10


def build_uri_regex(url_path: str) -> str:
    """
    基于 url_path 生成精准 URI 正则，只匹配路径部分（去掉 query string）。

    示例：
      /?page=1 and 1=1  ->  ^/$(\?.*)?$   (根路径，允许任意 query)
      /admin/login?id=1 ->  ^/admin/login(\?.*)?$
      /api/v1/user      ->  ^/api/v1/user(\?.*)?$
    """
    parsed = urlparse(url_path)
    path = parsed.path or "/"
    escaped = re.escape(path)
    # 精确匹配路径，query string 可选
    return f"^{escaped}(\\?.*)?$"


def build_whitelist_payload(log: dict) -> dict:
    """根据日志字段构建加白规则请求体"""
    method    = log.get("method", "GET")
    host      = log.get("host", "")
    url_path  = log.get("url_path", "/")
    module    = log.get("req_module") or log.get("module", "")
    event_id  = log.get("event_id", "")
    risk_level = log.get("req_risk_level_num") or log.get("risk_level_num", 3)
    uri_regex = build_uri_regex(url_path)

    print(f"  生成 URI 正则: {uri_regex}  (原始路径: {url_path})")

    return {
        "attack_type": None,
        "comment": f"消除误报 - {event_id}",
        "create_time": 0,
        "expire_time": 0,
        "id": 0,
        "action": "modify_module",
        "forbidden_page_config": None,
        "log_option": "Persistence",
        "is_enabled": True,
        "is_expired": False,
        "is_global": True,
        "last_update_time": 0,
        "pattern": {
            "$AND": [
                {"str": {"method": method}, "decode_methods": []},
                {"str": {"host": host},     "decode_methods": []},
                {"re":  {"urlpath": uri_regex}, "decode_methods": []},
            ]
        },
        "websites": [],
        "module_management": {
            "disabled": [module],
            "enabled": []
        },
        "risk_level": risk_level,
        "delay": 0,
        "percentage": 100,
        "cron_config": {
            "type": "all",
            "start": "00:00",
            "end": "23:59",
            "days": [],
            "start_timestamp": 0,
            "end_timestamp": 0
        },
        "req_rule_id": "",
        "rsp_rule_id": "",
        "duration": 1,
        "forward_address": {"host": "", "port": 80, "protocol": "http"},
        "session_method": {"param": "", "type": "src_ip"},
        "mark_flag": "",
        "priority": 0,
        "custom_fsl": "",
        "ignore_skip_remaining": False,
        "hook": 0,
        "is_protected": False
    }


def add_whitelist(log: dict):
    """根据日志信息调用加白接口"""
    payload = build_whitelist_payload(log)

    url = f"{BASE_URL}/api/ModifyModulePolicyRuleAPI"
    headers = {
        "API-TOKEN": API_TOKEN,
        "Content-Type": "application/json",
        "Referer": BASE_URL,   # strict-origin-when-cross-origin 需要同源 Referer
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT, verify=False)
        response.raise_for_status()

        result = response.json()
        if result.get("err"):
            print(f"加白失败: {result['err']}")
        else:
            print(f"加白成功: {result}")
        return result

    except ConnectionError:
        print(f"连接失败，请检查网络: {BASE_URL}")
    except Timeout:
        print(f"请求超时（超过 {TIMEOUT} 秒）")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            print("认证失败，请检查 API-TOKEN")
        elif status == 403:
            print("权限不足，请检查 Referer 或账号权限")
        else:
            print(f"请求失败，状态码: {status}，响应: {e.response.text}")
    except requests.exceptions.JSONDecodeError:
        print("响应解析失败，返回内容不是合法 JSON")
    except RequestException as e:
        print(f"请求异常: {e}")

    return None


if __name__ == "__main__":
    # 模拟从 fetch_logs.py 获取到的日志字段
    sample_log = {
        "event_id":        "09bac712b4d045bd84983c658a5d4d8a",
        "method":          "GET",
        "host":            "192.168.24.55",
        "url_path":        "/?page=1 and 1=1&id=1 order by 10",
        "req_module":      "m_sqli",
        "module":          "m_sqli",
        "req_risk_level_num": 3,
    }

    add_whitelist(sample_log)
