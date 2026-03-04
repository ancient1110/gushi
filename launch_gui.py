#!/usr/bin/env python3
"""跨平台 GUI 启动器：自动准备虚拟环境并启动 Streamlit。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_PATH = ROOT / "app.py"
VENV_DIR = ROOT / ".venv"


def _venv_python_path() -> Path:
    if sys.platform.startswith("win"):
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd, cwd=ROOT)


def _check_call(cmd: list[str]) -> None:
    subprocess.check_call(cmd, cwd=ROOT)


def _ensure_venv() -> Path:
    py = _venv_python_path()
    if py.exists():
        return py

    print("[INFO] 未检测到 .venv，正在创建虚拟环境...")
    _check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    return py


def _has_streamlit(python_bin: Path) -> bool:
    result = subprocess.run(
        [str(python_bin), "-c", "import streamlit"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _install_requirements(python_bin: Path) -> None:
    req = ROOT / "requirements.txt"
    if not req.exists():
        raise FileNotFoundError("未找到 requirements.txt")

    print("[INFO] 正在安装/更新依赖（requirements.txt）...")
    _check_call([str(python_bin), "-m", "pip", "install", "-r", str(req)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动行情采集 Streamlit 图形界面")
    parser.add_argument("--no-install", action="store_true", help="如果缺少依赖，不自动安装")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not APP_PATH.exists():
        print("[ERROR] 未找到 app.py，请确认当前目录正确。")
        return 1

    try:
        python_bin = _ensure_venv()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 创建虚拟环境失败: {exc}")
        return 1

    if not _has_streamlit(python_bin):
        if args.no_install:
            print("[ERROR] 当前 .venv 中未安装 streamlit，请先执行: .venv 环境 pip install -r requirements.txt")
            return 1
        try:
            _install_requirements(python_bin)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] 安装依赖失败: {exc}")
            print("[TIP] 可手动执行: .venv 对应 python -m pip install -r requirements.txt")
            return 1

    cmd = [str(python_bin), "-m", "streamlit", "run", str(APP_PATH)]
    print("启动命令:", " ".join(cmd))
    print("如果浏览器未自动打开，请复制终端中的 Local URL 到浏览器访问。")
    return _run(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
