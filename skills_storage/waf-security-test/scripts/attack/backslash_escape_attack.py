import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_backslash_escape(url, headers, pattern, success, fail, error):
    """
    斜杠反转译攻击测试
    """
    # 定义测试 payload
    data = {
        "id": '%u0073%u0065%u006c%u0065%u0063%u0074+1+from+t%23'
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url + 'show.php', headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "斜杠反转译", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )