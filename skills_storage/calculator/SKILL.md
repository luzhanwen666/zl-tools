---
name: calculator
description: >
  执行数学运算和表达式计算。适用于加减乘除、幂运算、三角函数、对数、复数等。
  当用户需要计算数值、转换单位、求解公式时使用此技能。
version: 1.0.0
allowed_tools: [python]
tags: [math, calculator, computation]
---

# 计算器技能

## 概述

使用 Python 执行任意数学运算。支持基本运算、三角函数、对数、复数、矩阵等。

## 工作流程

1. 理解用户的计算需求
2. 编写 Python 表达式调用 math 模块
3. 用 `python` 工具执行代码
4. 返回结果给用户

## 调用示例

```json
{"tool": "python", "args": {"code": "import math\nprint(2 + 3 * 4)\nprint(math.sin(math.pi/2))\nprint(math.sqrt(144))"}}
```

## 常用模式

### 基本运算
```python
print(2 + 3 * 4)       # 14
print((100 - 30) / 2)  # 35.0
print(2 ** 10)         # 1024
```

### 三角函数
```python
import math
print(math.sin(math.radians(30)))  # sin(30°)
print(math.cos(math.pi / 4))       # cos(45°)
print(math.tan(math.radians(45)))  # tan(45°)
```

### 对数与指数
```python
import math
print(math.log(100))       # 自然对数
print(math.log10(1000))    # 以10为底
print(math.exp(2))         # e^2
print(math.sqrt(256))      # 平方根
```

### 复数
```python
a = 3 + 4j
b = 1 - 2j
print(a + b)
print(a * b)
print(abs(a))  # 模
```

### 统计
```python
data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
import statistics
print(f"均值: {statistics.mean(data)}")
print(f"中位数: {statistics.median(data)}")
print(f"标准差: {statistics.stdev(data)}")
```
