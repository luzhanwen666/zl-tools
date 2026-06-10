import os
import base64
import requests
import re
from .utils import make_request_with_timeout, process_attack_response


def attack_fileupload(url, headers, pattern, success, fail, error):
    """
    文件上传攻击测试
    """
    # image 目录在 scripts/image/ 下，相对于本文件（attack/）向上一级
    image_path = os.path.join(os.path.dirname(__file__), '..', 'image', 'shell.txt')
    
    try:
        # 打开文件并确保句柄自动关闭（with上下文管理器）
        with open(image_path, 'rb') as f:
            files = {'file': f}
            # 使用统一的请求处理函数，但文件上传需要特殊处理
            try:
                response = requests.post(url + "fileupload/", headers=headers, files=files, timeout=3, verify=False)
                success_flag = True
                response_or_error = response
                status_code = response.status_code
            except requests.exceptions.Timeout:
                return "文件上传测试请求超时（超过3秒）", success, fail, error + 1, 0
            except requests.exceptions.ConnectionError:
                return "文件上传测试连接失败", success, fail, error + 1, 0
            except requests.exceptions.RequestException as e:
                return f"文件上传测试请求异常: {str(e)}", success, fail, error + 1, 0
            except Exception as e:
                return f"文件上传测试未知错误: {str(e)}", success, fail, error + 1, 0

        # 处理响应
        return process_attack_response(
            "文件上传", success_flag, response_or_error, status_code, 
            pattern, success, fail, error
        )

    except FileNotFoundError:
        # 单独捕获文件不存在异常，便于定位问题
        error += 1
        values = "文件上传测试文件不存在：{}".format(image_path)
        return values, success, fail, error, 0
    except Exception as e:
        # 捕获其他所有异常
        error += 1
        values = f"文件上传测试未知问题: {str(e)}"
        return values, success, fail, error, 0