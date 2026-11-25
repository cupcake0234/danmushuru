"""Build and validate a store-upload ZIP with manifest.json at its root."""

import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_browser_extension import main as build_scripts
from windows_extension_setup import EXTENSION_FILES


def main():
    build_scripts()
    package = ROOT / "browser_extension_ready"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    locale = manifest["default_locale"]
    messages = json.loads((package / "_locales" / locale / "messages.json").read_text(encoding="utf-8"))
    for field in ("name", "description"):
        value = manifest[field]
        if value.startswith("__MSG_") and value.endswith("__"):
            assert messages[value[6:-2]]["message"], f"Missing localized {field}"
    for relative in (*manifest["icons"].values(), manifest["background"]["service_worker"]):
        assert relative in EXTENSION_FILES, f"Required file excluded from ZIP: {relative}"
    output = ROOT / "dist" / f"DanmuLive-Edge-Extension-v{manifest['version']}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in EXTENSION_FILES:
            archive.write(package / relative, arcname=relative)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(EXTENSION_FILES)
        assert json.loads(archive.read("manifest.json")) == manifest
        for relative in EXTENSION_FILES:
            assert archive.read(relative) == (package / relative).read_bytes(), relative
    print(output)
    print(f"{len(EXTENSION_FILES)} files, {output.stat().st_size:,} bytes, default language: {locale}")


if __name__ == "__main__":
    main()
