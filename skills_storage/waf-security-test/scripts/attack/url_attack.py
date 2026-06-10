import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_url(url, headers, pattern, success, fail, error):
    """
    URL编码攻击测试
    """
    # 定义 URL 编码攻击 payload
    data = {
        "value": "1%2520or%25201%2520%3D%25201"
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "URL编码攻击", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )
