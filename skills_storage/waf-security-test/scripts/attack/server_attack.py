import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_server(url, headers, pattern, success, fail, error):
    """
    服务器响应测试
    """
    # 覆盖headers（保留你的原有逻辑，也可改用传入的headers）
    server_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, server_headers, method='GET'
    )
    
    # 处理响应
    return process_attack_response(
        "服务器响应检测模块", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )