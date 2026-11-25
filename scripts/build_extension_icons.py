"""Render the extension's simple vector microphone/chat icon at browser/store sizes."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "browser_extension_ready" / "icons"
SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect x="8" y="8" width="112" height="112" rx="28" fill="#2864dc"/>
  <rect x="25" y="28" width="78" height="62" rx="15" fill="white"/>
  <path d="M37 84V102L60 84Z" fill="white"/>
  <rect x="57" y="38" width="14" height="27" rx="7" fill="#2864dc"/>
  <path d="M49 59V62a15 15 0 0 0 30 0V59M64 77V83M56 83H72"
    fill="none" stroke="#2864dc" stroke-width="5" stroke-linecap="round"/>
</svg>
'''


def main():
    scale = 8
    image = Image.new("RGBA", (128 * scale, 128 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    blue = "#2864dc"

    def box(values):
        return tuple(round(value * scale) for value in values)

    draw.rounded_rectangle(box((8, 8, 120, 120)), radius=28 * scale, fill=blue)
    draw.rounded_rectangle(box((25, 28, 103, 90)), radius=15 * scale, fill="white")
    draw.polygon([box(point) for point in ((37, 84), (37, 102), (60, 84))], fill="white")
    draw.rounded_rectangle(box((57, 38, 71, 65)), radius=7 * scale, fill=blue)
    draw.arc(box((49, 47, 79, 77)), 0, 180, fill=blue, width=5 * scale)
    for points in (((49, 59), (49, 62)), ((79, 59), (79, 62)),
                   ((64, 77), (64, 83)), ((56, 83), (72, 83))):
        draw.line([box(point) for point in points], fill=blue, width=5 * scale)
    for x, y in ((49, 59), (79, 59), (56, 83), (72, 83)):
        draw.ellipse(box((x - 2.5, y - 2.5, x + 2.5, y + 2.5)), fill=blue)
    ICONS.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        image.resize((size, size), Image.Resampling.LANCZOS).save(ICONS / f"icon{size}.png")
    (ROOT / "assets" / "extension-icon.svg").write_text(SVG, encoding="utf-8")
    store = ROOT / "dist" / "edge-store-assets"
    store.mkdir(parents=True, exist_ok=True)
    image.resize((300, 300), Image.Resampling.LANCZOS).save(store / "extension-logo-300.png")
    print(f"Extension icons: {ICONS}")
    print(f"Store logo: {store / 'extension-logo-300.png'}")


if __name__ == "__main__":
    main()
