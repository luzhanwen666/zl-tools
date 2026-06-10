import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_csrf(url, headers, pattern, success, fail, error):
    """
    CSRF攻击测试
    """
    # 定义 CSRF 攻击参数
    data = {
        "content": "hello",
        "user": "hello"
    }

    # 保留原有 CSRF 测试专用请求头（若外部传入headers为空/需覆盖，可调整优先级）
    csrf_headers = {
        "Referer": "http://www.weixin.com/abc.html",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    # 合并外部传入的headers（外部headers优先级更高，可覆盖内置headers）
    csrf_headers.update(headers)

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url + "add", csrf_headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "CSRF攻击", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )