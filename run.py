#!/usr/bin/env python
"""
TV Proxy 启动脚本

运行方式:
  推荐: uv run run.py
  或者: uv run python run.py

说明:
  - 项目使用 src 布局,已通过 pyproject.toml 配置为可安装包
  - uv sync 会自动将 src 目录下的模块安装到虚拟环境
  - 无需手动添加 sys.path,直接从 main 导入即可
"""

import os
import uvicorn
from main import socket_app

# 导入并运行主应用
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)
