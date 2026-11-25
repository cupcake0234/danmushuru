"""Keep application data and process-local caches beside this project."""

import os
from pathlib import Path
import sys
import tempfile


def project_root():
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    base = Path(sys.executable).resolve().parent
    # Development builds live in dist; a shared portable folder is self-contained.
    if (base.name.lower() == "dist" and (base.parent / "windows_app.py").is_file()
            and (base.parent / "build_windows_exe.bat").is_file()):
        return base.parent
    return base


def data_dir():
    return project_root() / "data"


def configure_runtime_paths():
    root = project_root()
    cache = root / ".tools" / "cache"
    temporary = root / ".tools" / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(temporary)
    tempfile.tempdir = str(temporary)
    for name, relative in {
        "XDG_CACHE_HOME": "",
        "HF_HOME": "huggingface",
        "HF_HUB_CACHE": "huggingface/hub",
        "HUGGINGFACE_HUB_CACHE": "huggingface/hub",
        "MODELSCOPE_CACHE": "modelscope",
        "PIP_CACHE_DIR": "pip",
        "UV_CACHE_DIR": "uv",
        "PYINSTALLER_CONFIG_DIR": "",
    }.items():
        os.environ[name] = str(cache / relative)


configure_runtime_paths()
