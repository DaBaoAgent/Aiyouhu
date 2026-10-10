# -*- coding: utf-8 -*-
"""在开着系统代理的机器上运行 H3 脚本：强制直连 autodl.art。

本机系统代理会把 H3 的 HTTPS 请求拦成 SSL 断连（表现为提交/轮询/下载报 SSL 错误）。
本封装在**进程内**清空 HTTP(S)/ALL_PROXY 环境变量并设 NO_PROXY=*，再以 __main__
运行目标脚本；不改动系统或用户级代理设置。

用法：
    python skills/openclaw/autodl-h3-video/scripts/h3run.py \
        skills/openclaw/autodl-h3-video/scripts/h3_video.py -w multi_image --prompt "..." -i 图.jpg -d 6 -o out.mp4
"""
import os
import sys
import runpy

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

target, *rest = sys.argv[1:]
if not target:
    sys.exit("用法: python h3run.py <目标脚本.py> [脚本参数...]")
sys.argv = [target] + rest
runpy.run_path(target, run_name="__main__")
