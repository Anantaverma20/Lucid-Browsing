"""Trim white border from source image and save extension icons (16, 48, 128)."""
import sys
from pathlib import Path

from PIL import Image, ImageChops

OUT_DIR = Path(__file__).resolve().parent / "icons"

# Source: argv[1], or icon_source.png in this folder, or default path
def get_src():
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            return p
    local = Path(__file__).resolve().parent / "icon_source.png"
    if local.exists():
        return local
    default = Path(__file__).resolve().parent.parent / "assets" / "c__Users_Ananta_Verma_AppData_Roaming_Cursor_User_workspaceStorage_6be474e410f5b2e61504f148daf0877c_images_image-5fc95144-d3a5-4bc5-bf0e-9d22e97eff74.png"
    return default if default.exists() else None

def main():
    SRC = get_src()
    if not SRC or not SRC.exists():
        print("Source image not found. Place icon as BrowserPlugin/icon_source.png or pass path: python build_icons.py <path>")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert("RGBA")
    # Trim white/near-white border: pixels that differ from white
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    diff = ImageChops.difference(im, bg)
    # Also consider very light pixels as border (e.g. 248+)
    extrema = im.getextrema()
    # Simple approach: getbbox on diff (non-white pixels)
    bbox = diff.getbbox()
    if bbox:
        im = im.crop(bbox)
    for size in (16, 48, 128):
        resized = im.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(OUT_DIR / f"icon{size}.png")
        print(f"Saved {OUT_DIR / f'icon{size}.png'}")
    print("Done. Update manifest.json with icons/icon16.png, icon48.png, icon128.png")

if __name__ == "__main__":
    main()
