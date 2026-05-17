#!/usr/bin/env python3
"""Generate all iOS + PWA icon sizes from a single SVG-style design."""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import os

OUT_WWW = Path(__file__).resolve().parent.parent / "www" / "icons"
OUT_IOS = Path(__file__).resolve().parent.parent / "icons"
OUT_WWW.mkdir(parents=True, exist_ok=True)
OUT_IOS.mkdir(parents=True, exist_ok=True)

# Coursera-style blue gradient brand
BLUE_TOP = (0, 86, 210)        # #0056D2
BLUE_BOTTOM = (29, 78, 216)    # #1D4ED8
GOLD = (251, 191, 36)          # #FBBF24
WHITE = (255, 255, 255)

# iOS App icon sizes (px) — required for Xcode AppIcon.appiconset
IOS_SIZES = {
    "icon-1024.png": 1024,           # App Store
    "icon-180.png": 180,             # iPhone @3x
    "icon-167.png": 167,             # iPad Pro
    "icon-152.png": 152,             # iPad @2x
    "icon-120.png": 120,             # iPhone @2x
    "icon-87.png": 87,               # Settings @3x
    "icon-80.png": 80,               # Spotlight @2x
    "icon-76.png": 76,               # iPad
    "icon-60.png": 60,               # iPhone
    "icon-58.png": 58,               # Settings @2x
    "icon-40.png": 40,               # Spotlight
    "icon-29.png": 29,               # Settings
    "icon-20.png": 20,               # Notifications
}

# PWA / Web icons
PWA_SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon-180.png": 180,
    "apple-touch-icon-167.png": 167,
    "apple-touch-icon-152.png": 152,
    "apple-touch-icon-120.png": 120,
}


def make_gradient(size):
    """Vertical blue gradient background."""
    img = Image.new("RGB", (size, size), BLUE_TOP)
    px = img.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(BLUE_TOP[0] * (1 - t) + BLUE_BOTTOM[0] * t)
        g = int(BLUE_TOP[1] * (1 - t) + BLUE_BOTTOM[1] * t)
        b = int(BLUE_TOP[2] * (1 - t) + BLUE_BOTTOM[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def add_shine(img):
    """Add subtle radial highlight top-left."""
    size = img.size[0]
    overlay = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    # soft white circle
    radius = int(size * 0.7)
    cx, cy = int(size * 0.22), int(size * 0.18)
    for r in range(radius, 0, -1):
        alpha = int(36 * (1 - r / radius))
        if alpha <= 0: break
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=size // 25))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def get_font(size_px):
    """Try several font paths; fall back to default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVu-Sans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size_px)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_logo(img):
    """Draw 'AJ' monogram + small badge."""
    size = img.size[0]
    draw = ImageDraw.Draw(img)

    # Subtle inner stroke for "card" look
    inset = max(int(size * 0.04), 1)
    draw.rounded_rectangle(
        [inset, inset, size - inset, size - inset],
        radius=int(size * 0.12),
        outline=(255, 255, 255, 30),
        width=max(1, int(size * 0.004))
    )

    # Monogram "AJ"
    text = "AJ"
    font_size = int(size * 0.52)
    font = get_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - int(size * 0.04)
    # text shadow
    sh = max(1, int(size * 0.008))
    draw.text((tx + sh, ty + sh), text, fill=(0, 0, 0, 70), font=font)
    draw.text((tx, ty), text, fill=WHITE, font=font)

    # Gold accent bar bottom (Coursera-ish vibe)
    bar_h = max(int(size * 0.05), 2)
    bar_w = int(size * 0.32)
    bar_x = (size - bar_w) // 2
    bar_y = int(size * 0.82)
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        radius=bar_h // 2,
        fill=GOLD
    )
    return img


def render_icon(size, path):
    img = make_gradient(size).convert("RGBA")
    img = add_shine(img)
    img = draw_logo(img)
    # Convert to RGB for solid background (iOS prefers no alpha)
    final = Image.new("RGB", img.size, BLUE_TOP)
    final.paste(img, (0, 0), img)
    final.save(path, "PNG", optimize=True)
    return path


def main():
    print("Rendering icons...")
    for name, sz in {**IOS_SIZES, **PWA_SIZES}.items():
        # Save to www/icons (used by PWA + Capacitor)
        p1 = OUT_WWW / name
        render_icon(sz, p1)
    # Also copy critical sizes to /icons/ for Xcode AppIcon.appiconset
    for name in IOS_SIZES:
        src = OUT_WWW / name
        dst = OUT_IOS / name
        Image.open(src).save(dst, "PNG", optimize=True)
    print(f"OK · {len(IOS_SIZES)} iOS icons + {len(PWA_SIZES)} PWA icons rendered")
    print(f"  www/icons/  : {OUT_WWW}")
    print(f"  icons/      : {OUT_IOS}")


if __name__ == "__main__":
    main()
