# import requests
# import re
#
#
# def make_request_with_timeout(url, headers, method='GET', data=None, params=None, timeout=3):
#     """
#     统一的请求处理函数，包含超时和错误处理
#
#     Args:
#         url: 目标URL
#         headers: 请求头
#         method: HTTP方法 (GET, POST等)
#         data: POST数据
#         params: GET参数
#         timeout: 超时时间（秒）
#
#     Returns:
#         tuple: (success, response_or_error_msg, status_code)
#     """
#     try:
#         if method.upper() == 'POST':
#             response = requests.post(url, headers=headers, data=data, timeout=timeout, verify=False)
#         else:
#             response = requests.get(url, headers=headers, params=params, timeout=timeout, verify=False)
#
#         return True, response, response.status_code
#
#     except requests.exceptions.Timeout:
#         return False, "请求超时（超过3秒）", 408
#     except requests.exceptions.ConnectionError:
#         return False, "连接失败", 503
#     except requests.exceptions.RequestException as e:
#         return False, f"请求异常: {str(e)}", 500
#     except Exception as e:
#         return False, f"未知错误: {str(e)}", 500
#
#
# def process_attack_response(attack_name, success_flag, response_or_error, status_code, pattern, success, fail, error):
#     """
#     统一处理攻击响应结果
#
#     Args:
#         attack_name: 攻击类型名称
#         success_flag: 请求是否成功
#         response_or_error: 响应对象或错误消息
#         status_code: HTTP状态码
#         pattern: 匹配模式
#         success: 成功计数
#         fail: 失败计数
#         error: 错误计数
#
#     Returns:
#         tuple: (message, success, fail, error, match_result)
#     """
#     if not success_flag:
#         # 请求失败
#         error += 1
#         values = f"{attack_name}测试{response_or_error}"
#         return values, success, fail, error, 0
#
#     # 请求成功，检查状态码
#     if status_code >= 500:
#         error += 1
#         values = f"{attack_name}测试服务器错误 (状态码: {status_code})"
#         return values, success, fail, error, 0
#
#     # 检查响应内容中的拦截标识
#     try:
#         matches = re.findall(pattern, response_or_error.text)
#         if matches:
#             for match in matches:
#                 values = f"{attack_name}测试拦截成功，event_id: {match}"
#                 success += 1
#                 return values, success, fail, error, match
#         else:
#             values = f"{attack_name}测试未被拦截"
#             fail += 1
#             return values, success, fail, error, 0
#     except Exception as e:
#         error += 1
#         values = f"{attack_name}测试响应解析错误: {str(e)}"
#         return values, success, fail, error, 0


import requests
import re


def make_request_with_timeout(url, headers, method='GET', data=None, params=None, timeout=3, allow_redirects=False,
                              max_redirects=30):
    """
    统一的请求处理函数，包含超时、错误处理和重定向配置

    Args:
        url: 目标URL
        headers: 请求头
        method: HTTP方法 (GET, POST等)
        data: POST数据
        params: GET参数
        timeout: 超时时间（秒）
        allow_redirects: 是否允许跟随重定向（默认True）
        max_redirects: 最大重定向跟随次数（默认30，可自定义）

    Returns:
        tuple: (success, response_or_error_msg, status_code)
    """
    try:
        # 自定义重定向适配器，设置最大重定向次数
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=0)  # 重试次数设为0，避免与重定向冲突
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        if method.upper() == 'POST':
            response = session.post(
                url,
                headers=headers,
                data=data,
                timeout=timeout,
                verify=False,
                allow_redirects=allow_redirects,  # 控制是否跟随重定向
                # requests默认通过urllib3控制最大重定向次数，此处通过session间接生效，或直接依赖默认30次
            )
        else:
            response = session.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
                verify=False,
                allow_redirects=allow_redirects
            )

        # 即使是重定向状态码（3xx），也返回请求成功

        return True, response, response.status_code

    except requests.exceptions.Timeout:
        return False, "请求超时（超过3秒）", 408
    except requests.exceptions.TooManyRedirects:
        # 单独捕获重定向次数超出异常（可选：可自定义提示信息）
        return False, f"重定向次数超出限制（最大{max_redirects}次）", 310
    except requests.exceptions.ConnectionError:
        return False, "连接失败", 503
    except requests.exceptions.RequestException as e:
        return False, f"请求异常: {str(e)}", 500
    except Exception as e:
        return False, f"未知错误: {str(e)}", 500


def process_attack_response(attack_name, success_flag, response_or_error, status_code, pattern, success, fail, error):
    """
    统一处理攻击响应结果，将3xx重定向视为正常请求

    Args:
        attack_name: 攻击类型名称
        success_flag: 请求是否成功
        response_or_error: 响应对象或错误消息
        status_code: HTTP状态码
        pattern: 匹配模式
        success: 成功计数
        fail: 失败计数
        error: 错误计数

    Returns:
        tuple: (message, success, fail, error, match_result)
    """
    if not success_flag:
        # 只有请求本身失败（超时、连接失败、重定向超限等）才计数错误
        error += 1
        values = f"{attack_name}测试{response_or_error}"
        return values, success, fail, error, 0

    # 请求成功（包括3xx重定向、2xx成功、4xx客户端错误），排除5xx服务器错误
    if status_code >= 500:
        error += 1
        values = f"{attack_name}测试服务器错误)"
        return values, success, fail, error, 0
    # 排除3xx重定向的错误判定，将其视为正常请求
    elif 300 <= status_code < 400:
        # 重定向视为正常请求，继续执行后续的拦截标识匹配
        values_prefix = f"{attack_name}测试请求正常"
    else:
        # 2xx/4xx状态码，正常处理
        values_prefix = f"{attack_name}测试请求正常"

    # 检查响应内容中的拦截标识（重定向请求也会执行此逻辑）
    try:
        matches = re.findall(pattern, response_or_error.text)
        if matches:
            for match in matches:
                values = f"{values_prefix}，拦截成功，event_id: {match}"
                success += 1
                return values, success, fail, error, match
        else:
            values = f"{values_prefix}，未被拦截"
            fail += 1
            return values, success, fail, error, 0
    except Exception as e:
        error += 1
        values = f"{attack_name}测试响应解析错误: {str(e)}"
        return values, success, fail, error, 0