import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_robot(url, headers, pattern, success, fail, error):
    """
    机器人检测攻击测试
    """
    # 定义机器人检测专用请求头（合并外部传入的headers，外部优先级更高）
    robot_headers = {
        "User-Agent": "Sqlmap",
    }


    # 发送请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, robot_headers, method='GET'
    )
    
    # 处理响应
    return process_attack_response(
        "机器人检测模块", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )