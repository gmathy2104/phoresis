"""Generate the Phoresis app-icon raster outputs from a Pillow draw routine.

Avoids the ImageMagick dependency. The geometry mirrors `assets/icons/phoresis.svg`:
- 416x416 outer rounded square (radius 80) on a 512x512 canvas, fill #0f172a
- 112x312 lane silhouette (rx=16) at (200,100), gradient blue->purple->magenta @ 18% alpha
- Three horizontal bands (112x22, rx=6) at y=160 (#3b82f6), y=240 (#a855f7), y=320 (#ec4899)

Outputs:
- assets/icons/phoresis-512.png  (512x512)
- assets/icons/apple-touch-icon.png  (180x180)
- assets/icons/phoresis.ico  (multi-res 16/24/32/48/64/128/256)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 512
OUT_DIR = Path("assets/icons")


def _hex(c: str) -> tuple[int, int, int, int]:
    """Hex string '#rrggbb' -> (r, g, b, 255)."""
    h = c.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _draw_lane_gradient(img: Image.Image, x: int, y: int, w: int, h: int, alpha: float = 0.18) -> None:
    """Vertical 3-stop gradient: #3b82f6 -> #a855f7 -> #ec4899, multiplied by `alpha`."""
    stops = [(0.0, _hex("#3b82f6")), (0.5, _hex("#a855f7")), (1.0, _hex("#ec4899"))]
    a = round(alpha * 255)
    for row in range(h):
        t = row / max(h - 1, 1)
        # Find the two stops bracketing t
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0) if t1 > t0 else 0
                r = round(c0[0] + (c1[0] - c0[0]) * k)
                g = round(c0[1] + (c1[1] - c0[1]) * k)
                b = round(c0[2] + (c1[2] - c0[2]) * k)
                # PIL doesn't draw alpha rectangles directly on RGB - overlay via paste
                row_img = Image.new("RGBA", (w, 1), (r, g, b, a))
                img.alpha_composite(row_img, (x, y + row))
                break


def _draw_rounded_rect_mask(canvas_size: int, box: tuple[int, int, int, int], radius: int) -> Image.Image:
    """Return a 1-bit mask the size of the canvas with a rounded rect cut into it."""
    mask = Image.new("L", (canvas_size, canvas_size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def render_canvas() -> Image.Image:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Outer rounded square
    d.rounded_rectangle((48, 48, 48 + 416, 48 + 416), radius=80, fill=_hex("#0f172a"))

    # Lane silhouette - gradient at 18% alpha, clipped to a rounded-rect mask
    lane_layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    _draw_lane_gradient(lane_layer, 200, 100, 112, 312, alpha=0.18)
    lane_mask = _draw_rounded_rect_mask(CANVAS, (200, 100, 200 + 112, 100 + 312), radius=16)
    img.paste(lane_layer, (0, 0), mask=lane_mask)

    # Three bands
    for y, color in ((160, "#3b82f6"), (240, "#a855f7"), (320, "#ec4899")):
        d.rounded_rectangle((200, y, 200 + 112, y + 22), radius=6, fill=_hex(color))

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = render_canvas()

    # 512 PNG
    base.save(OUT_DIR / "phoresis-512.png", format="PNG")

    # Apple touch icon (180x180)
    base.resize((180, 180), Image.LANCZOS).save(OUT_DIR / "apple-touch-icon.png", format="PNG")

    # Multi-resolution ICO
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(OUT_DIR / "phoresis.ico", format="ICO", sizes=sizes)

    print(f"Wrote: phoresis-512.png, apple-touch-icon.png, phoresis.ico ({len(sizes)} sizes)")


if __name__ == "__main__":
    main()
