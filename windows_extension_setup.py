"""Prepare the bundled browser extension and open Chromium extension pages."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


EXTENSION_FILES = (
    "manifest.json", "service_worker.js", "generated/bilibili.js",
    "generated/douyu.js", "generated/douyin.js",
)
BROWSERS = {
    "edge": ("msedge.exe", "edge://extensions"),
    "chrome": ("chrome.exe", "chrome://extensions"),
}


def extension_source():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "browser_extension_ready"


def extension_folder():
    data_home = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return data_home / "DanmuLive" / "browser_extension_ready"


def prepare_extension(source=None, destination=None):
    source = Path(source) if source is not None else extension_source()
    destination = Path(destination) if destination is not None else extension_folder()
    for relative_path in EXTENSION_FILES:
        source_file = source / relative_path
        if not source_file.is_file():
            raise FileNotFoundError(f"浏览器扩展文件缺失：{source_file}")
    for relative_path in EXTENSION_FILES:
        source_file = source / relative_path
        destination_file = destination / relative_path
        if destination_file.is_file() and destination_file.read_bytes() == source_file.read_bytes():
            continue
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
    return destination


def open_extensions_page(browser):
    import winreg

    executable, page = BROWSERS[browser]
    path = None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}") as key:
                path = winreg.QueryValueEx(key, "")[0]
            if Path(path).is_file():
                break
        except OSError:
            pass
        path = None
    if path is None:
        path = shutil.which(executable)
    if path is None:
        raise FileNotFoundError(f"未找到 {browser.title()} 浏览器，请确认已安装。")
    subprocess.Popen([str(path), page])
