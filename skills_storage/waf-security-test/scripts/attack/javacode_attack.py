import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_javacode(url, headers, pattern, success, fail, error):
    """
    Java代码执行攻击测试
    """
    # 定义 Java 代码执行攻击专用请求头（合并外部传入的headers，外部优先级更高）
    javacode_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Content-Type": "%{#context['com.opensymphony.xwork.dispatcher.HttpServletResponse']}Multipart",
    }
    # 合并外部headers，兼容灵活调用
    javacode_headers.update(headers)

    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url + 'index.php', javacode_headers, method='GET'
    )
    
    # 处理响应
    return process_attack_response(
        "Java代码执行", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )