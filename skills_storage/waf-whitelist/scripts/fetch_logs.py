import requests
import urllib3
from requests.exceptions import ConnectionError, Timeout, RequestException

# 跳过自签名证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
BASE_URL = "https://192.168.24.55:9443"  # 替换为实际域名
API_TOKEN = "X7wQOfQhXRUZH1FOpSZnr3r4gkoa5gbloobRYvxe"      # 替换为实际 token

TIMEOUT = 10  # 请求超时时间（秒）


def print_log(data: dict):
    """格式化输出日志详情"""
    if data.get("err"):
        print(f"接口返回错误: {data['err']}")
        return

    logs = data.get("data", [])
    if not logs:
        print("未查询到相关日志")
        return

    log = logs[0]

    # 请求头单独处理，去掉末尾多余空行
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
    print(f"  协议           : {log.get('scheme').upper()}")
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


def fetch_log_detail(event_id: str, timestamp: str):
    """
    通过 event_id 获取对应的日志详情

    :param event_id: 事件 ID
    :param timestamp: 时间戳
    """
    if not event_id or not timestamp:
        raise ValueError("event_id 和 timestamp 不能为空")

    url = f"{BASE_URL}/api/FilterV2API"

    headers = {
        "API-TOKEN": API_TOKEN,
        "Content-Type": "application/json",
    }

    params = {
        "scope": "log:detect_log:detail",
        "event_id__exact": event_id,
        "timestamp__exact": timestamp,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT, verify=False)
        response.raise_for_status()  # 4xx / 5xx 统一抛出 HTTPError

        data = response.json()
        print_log(data)
        return data

    except ValueError as e:
        print(f"参数错误: {e}")
    except ConnectionError:
        print(f"连接失败，请检查网络或域名是否正确: {BASE_URL}")
    except Timeout:
        print(f"请求超时（超过 {TIMEOUT} 秒），请稍后重试")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            print("认证失败，请检查 API-TOKEN 是否正确")
        elif status == 403:
            print("权限不足，请确认账号拥有 Website And Security Policy Management 权限")
        elif status == 404:
            print(f"未找到对应日志，event_id: {event_id}")
        else:
            print(f"请求失败，状态码: {status}，响应内容: {e.response.text}")
    except requests.exceptions.JSONDecodeError:
        print("响应内容解析失败，返回的不是合法 JSON")
        print(f"原始响应: {response.text}")
    except RequestException as e:
        print(f"请求异常: {e}")

    return None


if __name__ == "__main__":
    event_id = "09bac712b4d045bd84983c658a5d4d8a"
    timestamp = "1775735679"

    fetch_log_detail(event_id, timestamp)
