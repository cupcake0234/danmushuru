"""Assemble a shareable Windows x64 folder with a clean config and offline model."""

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_store import MODEL_FILES, MODEL_NAME, _valid_file, managed_model_dir
from windows_extension_setup import EXTENSION_FILES


GUIDE = """直播弹幕控制台 · Windows x64 完整便携版

一、开始使用
1. 将整个 ZIP 解压到有写入权限的 D 盘或其他非 C 盘文件夹。不要直接在 ZIP 中运行。
2. 双击 DanmuLive.exe（或“启动程序.bat”）。不需要安装 Python、CUDA 或另行下载模型。
3. 本包面向 Windows 10/11 64 位（Intel/AMD x64）。32 位 Windows 不适用。

二、首次连接浏览器
1. 在 Edge 或 Chrome 中登录直播平台，并打开哔哩哔哩、斗鱼或抖音直播间。
2. 在程序中点击“安装浏览器扩展”，打开对应浏览器的扩展管理页。
3. 开启开发者模式，选择“加载解压缩的扩展程序”，加载本包中的 data\\browser_extension_ready。
   文件夹选择窗口可能不显示文件，选中上述文件夹即可。每个浏览器只需安装一次。
4. 回到程序，手动选择直播间，或启用“自动跟随”以跟随浏览器正在观看的直播页面。
5. 文件夹搬家后，浏览器仍可能记着旧的扩展路径，需移除旧扩展并加载新位置。

三、文字和语音
可直接输入文字发送弹幕。本包默认使用本地 SenseVoiceSmall INT8，模型已内置，
语音识别在 CPU 上离线运行。点击“开始监听”前，请确认麦克风可用、选定直播间可以发送。
在“语音设置”中可调整语言和音量门限；也可自行填写百炼 Key，改用云端识别。
本包使用全新配置，没有打包开发者的 Key、浏览器账号或个人设置。
观看直播、发送弹幕和云端识别需要联网；本地语音识别无需联网。

四、移动、保存和分享
请始终移动整个文件夹，保留 DanmuLive.exe、_internal、data 和许可证文件。
data\\models 保存模型，data\\config.local.json 保存设置，data\\browser_extension_ready 保存扩展。
内置模型路径是相对于 data 的路径，修改语音设置后也可随整个文件夹移动。
运行库放在 _internal，不会启动后再解压到 C 盘；缓存和临时文件位于本包的 .tools 中。
以后转发自己使用过的文件夹时，请先清空配置里的个人云端 Key。

五、环境检查
遇到启动、语音或模型问题，可双击“环境检查.bat”。它检查图形运行库、音频运行库、
扩展文件、模型校验值和本地 CPU 推理，结果写入“self-check.json”。
检查不打开麦克风，不连接浏览器，也不发送弹幕。

六、模型出处
SenseVoiceSmall：FunAudioLLM / FunASR；ONNX 转换与 INT8 模型发布：sherpa-onnx / csukuangfj。
模型下载来源和 SHA-256 见 package-manifest.json；相关协议见 third_party_licenses。
https://huggingface.co/FunAudioLLM/SenseVoiceSmall
https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
"""


def copy_microsoft_runtime(package):
    """Include app-local VC/MFC dependencies that can already exist on the build PC."""
    import pefile
    internal = package / "_internal"
    system = Path(os.environ["SystemRoot"]) / "System32"
    pending = [p for p in internal.rglob("*") if p.suffix.lower() in (".pyd", ".dll")]
    pending.append(package / "DanmuLive.exe")
    copied = set()
    while pending:
        file = pending.pop()
        pe = pefile.PE(str(file), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                             pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        entries = getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
        for entry in entries:
            name = entry.dll.decode("ascii").lower()
            if not re.match(r"(?:mfc|msvcp|vcruntime|concrt|vcomp)\d.*\.dll$", name) or name in copied:
                continue
            source = system / name
            if not source.is_file():
                if any(internal.rglob(name)):
                    copied.add(name)
                    continue
                raise FileNotFoundError(f"Missing redistributable runtime: {name}")
            target = internal / name
            shutil.copy2(source, target)
            copied.add(name)
            pending.append(target)
        pe.close()
    return sorted(copied)


def copy_licenses(package):
    target = package / "third_party_licenses"
    shutil.copytree(ROOT / "assets/third-party", target)
    for dist in metadata.distributions():
        name = dist.metadata.get("Name", "unknown")
        for relative in dist.files or []:
            parts = relative.parts
            if ".." in parts or not any(part.endswith(".dist-info") for part in parts):
                continue
            if not ("licenses" in parts or relative.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))):
                continue
            source = Path(dist.locate_file(relative))
            if source.is_file():
                destination = target / re.sub(r"[^a-zA-Z0-9_.-]", "_", name) / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError(python_license)
    shutil.copy2(python_license, target / "PYTHON_LICENSE.txt")
    (target / "MICROSOFT_RUNTIME_SOURCE.txt").write_text(
        "Microsoft Visual C++ / MFC runtime libraries are included app-locally.\n"
        "https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files\n"
        "https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution\n", encoding="utf-8")


def assemble(destination):
    destination = destination.resolve()
    if not destination.is_relative_to(ROOT) or destination == ROOT or destination.exists():
        raise ValueError("Use a new output folder inside this project")
    runtime = ROOT / ".tools/portable-dist/DanmuLive"
    if not (runtime / "_internal/python312.dll").is_file():
        raise FileNotFoundError("Build the onedir application first")
    model = managed_model_dir()
    for spec in MODEL_FILES:
        if not _valid_file(model / spec.name, spec, None):
            raise ValueError(f"Model verification failed: {spec.name}")
    destination.mkdir(parents=True)
    shutil.copy2(runtime / "DanmuLive.exe", destination / "DanmuLive.exe")
    shutil.copytree(runtime / "_internal", destination / "_internal",
                    ignore=shutil.ignore_patterns("__pycache__"))
    vc_files = copy_microsoft_runtime(destination)
    data = destination / "data"
    model_target = data / "models" / MODEL_NAME
    model_target.mkdir(parents=True)
    for spec in MODEL_FILES:
        shutil.copy2(model / spec.name, model_target / spec.name)
    for relative in EXTENSION_FILES:
        target = data / "browser_extension_ready" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "browser_extension_ready" / relative, target)
    # Only use the public template: local credentials/settings are never copied.
    config = json.loads((ROOT / "config.local.example.json").read_text(encoding="utf-8"))
    config.update(voice_provider="sensevoice", local_model_dir="models/" + MODEL_NAME,
                  dashscope_api_key="")
    (data / "config.local.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / "使用说明.txt").write_text(GUIDE.replace("\n", "\r\n"), encoding="utf-8-sig")
    (destination / "启动程序.bat").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0DanmuLive.exe"\r\n', encoding="ascii")
    (destination / "环境检查.bat").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\n'
        'start "" /wait "%~dp0DanmuLive.exe" --self-check "%~dp0self-check.json"\r\n'
        'if exist "%~dp0self-check.json" start "" notepad.exe "%~dp0self-check.json"\r\n', encoding="ascii")
    copy_licenses(destination)
    manifest = {"platform": "Windows x64", "model": MODEL_NAME,
                "model_source": "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
                "microsoft_runtime_files": vc_files, "files": []}
    for file in sorted(destination.rglob("*")):
        if file.is_file():
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest["files"].append({"path": file.relative_to(destination).as_posix(),
                                      "bytes": file.stat().st_size, "sha256": digest})
    (destination / "package-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = destination.with_suffix(".zip")
    if archive.exists():
        raise FileExistsError(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in sorted(destination.rglob("*")):
            if file.is_file():
                output.write(file, file.relative_to(destination.parent))
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(checksum + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"folder": str(destination), "zip": str(archive), "bytes": archive.stat().st_size,
                      "files": len(manifest["files"]) + 1, "sha256": checksum}, ensure_ascii=False))
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release/DanmuLive-Windows-x64-Portable-20261125")
    assemble(parser.parse_args().output)
