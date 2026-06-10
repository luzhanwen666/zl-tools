import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_more(url, headers, pattern, success, fail, error):
    """
    多层编码解析攻击测试
    """
    # 定义多层编码解析攻击 payload
    data = {
        "value": "JTI2JTIzeDNDJTNCYSUyMGhyZWYlM0QlMjYlMjN4MjclM0IlMjAlNUN0JTIwamF2YXNjcmlwdCUzQWFsZXJ0JTI4MSUyOSUyMCUyNiUyM3gyNyUzQiUyMCUyZiUyNiUyM3gzRSUzQg=="
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "多层编码解析", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )