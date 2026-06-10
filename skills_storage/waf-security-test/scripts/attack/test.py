import re


def complete_url_slash(url):
    """
    补全URL末尾的/（无则加，有则跳过）
    :param url: 前端传入的原始URL
    :return: 补全后的URL
    """
    if not url:
        return url  # 空值直接返回

    # 去除末尾空白字符
    trimmed_url = url.strip()
    # 正则匹配（与JS逻辑一致，忽略大小写）
    reg = re.compile(r'^(https?:\/\/[^\/]+)$', re.IGNORECASE)

    if reg.match(trimmed_url):
        # 无末尾/，补充/
        return f"{trimmed_url}/"
    # 已有/，直接返回
    return trimmed_url


# 测试示例
print(complete_url_slash('http://1.1.1.1'))  # 输出：http://1.1.1.1/
print(complete_url_slash('http://1.1.1.1:8111'))  # 输出：http://1.1.1.1:8111/
print(complete_url_slash('http://1.1.1.1:8111/'))  # 输出：http://1.1.1.1:8111/
print(complete_url_slash('https://www.example.com'))  # 输出：https://www.example.com/
print(complete_url_slash('https://www.example.com/'))  # 输出：https://www.example.com/