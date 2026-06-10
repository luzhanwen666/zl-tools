import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_onesix(url, headers, pattern, success, fail, error):
    """
    16进制编码攻击测试
    """
    # 定义 16进制解析攻击 payload
    data = {
        "id": '0x3c696d67207372633d78206f6e6572726f723d616c65727428646f63756d656e742e636f6f6b6965293e'
    }

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url + 'show.php', headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "16进制编码", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )