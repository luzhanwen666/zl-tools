import os
os.environ["BASE_URL"] = "https://192.168.24.55:9443"
os.environ["API_TOKEN"] = "X7wQOfQhXRUZH1FOpSZnr3r4gkoa5gbloobRYvxe"

import sys
sys.path.insert(0, ".")

import main as m

# 同步环境变量到 main 模块的全局变量
m.BASE_URL  = os.environ["BASE_URL"]
m.API_TOKEN = os.environ["API_TOKEN"]

m.run("5543f673f36c4f818d375f7b095dde18")
