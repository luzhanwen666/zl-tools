import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_json(url, headers, pattern, success, fail, error):
    """
    JSON解析攻击测试
    """
    # 定义 JSON 解析攻击 payload
    data = {
        "id": '{"id":"31%20and%201=1"}'
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url + 'show.php', headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "JSON解析", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )