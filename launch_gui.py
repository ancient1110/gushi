#!/usr/bin/env python3
"""跨平台 GUI 启动器：避免依赖 PATH 中的 streamlit 命令。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).with_name("app.py")
    if not app_path.exists():
        print("未找到 app.py，请确认当前目录正确。")
        return 1

    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    print("启动命令:", " ".join(cmd))
    print("如果浏览器未自动打开，请复制终端中的 Local URL 到浏览器访问。")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
