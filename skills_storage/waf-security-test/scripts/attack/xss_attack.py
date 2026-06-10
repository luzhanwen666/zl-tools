import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_xss(url, headers, pattern, success, fail, error):
    """
    XSS攻击测试
    """
    # 定义XSS测试payload
    data = {
        "url": "<script>alert(document.cookie)</script>"
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "XSS攻击", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )
