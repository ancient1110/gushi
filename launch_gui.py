#!/usr/bin/env python3
"""跨平台 GUI 启动器：避免依赖 PATH 中的 streamlit 命令。"""

from __future__ import annotations

import subprocess
import sys
import importlib.util
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).with_name("app.py")
    if not app_path.exists():
        print("未找到 app.py，请确认当前目录正确。")
        return 1

    if importlib.util.find_spec("streamlit") is None:
        print("当前 Python 环境未安装 streamlit，无法启动图形界面。")
        print("请先执行以下命令安装依赖后再重试：")
        print(f"  {sys.executable} -m pip install -r requirements.txt")
        print("或仅安装 Streamlit：")
        print(f"  {sys.executable} -m pip install streamlit")
        return 1

    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    print("启动命令:", " ".join(cmd))
    print("如果浏览器未自动打开，请复制终端中的 Local URL 到浏览器访问。")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
