import requests
import re
from .utils import make_request_with_timeout, process_attack_response

def attack_sql(url, headers, pattern, success, fail, error):
    """
    SQL注入攻击测试
    """
    data = {
        "page": "1 and 1=1",
        "id": "1 order by 10"
    }
    
    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, headers, method='GET', params=data
    )
    
    # 处理响应
    return process_attack_response(
        "SQL注入", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )
