"""Build the Chromium extension's static page scripts from source files."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "browser_extension_ready"
OUTPUT = PACKAGE / "generated"
SOURCES = {
    "bilibili": "web_actions/browser_actions.js",
    "douyu": "web_actions/douyu_actions.js",
    "douyin": "web_actions/douyin_web_actions.js",
}


def main():
    OUTPUT.mkdir(exist_ok=True)
    for platform, source in SOURCES.items():
        script = (ROOT / source).read_text(encoding="utf-8")
        if script.count("__PAYLOAD_JSON__") != 1:
            raise ValueError(f"{source}: expected exactly one request placeholder")
        output = script.replace("__PAYLOAD_JSON__", "globalThis.__danmuPayload")
        (OUTPUT / f"{platform}.js").write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
