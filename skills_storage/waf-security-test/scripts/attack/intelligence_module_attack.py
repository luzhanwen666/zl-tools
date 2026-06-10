import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_intelligence_module(url, headers, pattern, success, fail, error):
    """
    情报模块攻击测试
    """
    # 构造请求URL，尝试访问/etc/passwd
    target_url = url + "/etc/passwd"
    
    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        target_url, headers, method='GET'
    )
    
    # 处理响应
    return process_attack_response(
        "情报模块", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )