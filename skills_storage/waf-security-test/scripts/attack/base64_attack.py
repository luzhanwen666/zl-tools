import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_base64(url, headers, pattern, success, fail, error):
    """
    Base64编码攻击测试
    """
    # 定义 base64 攻击 payload
    data = {
        "value": "MSUyMG9yJTIwMSUyMD0lMjAx"
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "Base64编码", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )