from __future__ import annotations

import math
import os
import tkinter as tk
from typing import Tuple, Optional

from PIL import Image, ImageDraw, ImageTk, ImageFont, ImageFilter, ImageOps

# -----------------------------------------------------------------------------
# Paths & caching
# -----------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_HOUSE_PATH = os.path.join(_THIS_DIR, "house.png")

_loaded_house: Optional[Image.Image] = None  # cached original RGBA
_loaded_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def _load_house_original() -> Image.Image:
    global _loaded_house
    if _loaded_house is None:
        if not os.path.exists(_HOUSE_PATH):
            raise FileNotFoundError(f"house.png not found at: {_HOUSE_PATH}")
        _loaded_house = Image.open(_HOUSE_PATH).convert("RGBA")
    return _loaded_house


# -----------------------------------------------------------------------------
# Font helpers (used only in demo’s time badge; safe to keep)
# -----------------------------------------------------------------------------
_FONT_CANDIDATES = ("Segoe UI", "SegoeUI", "Arial", "DejaVuSansMono", "DejaVuSans")
def _font(size: int) -> ImageFont.FreeTypeFont:
    if size in _loaded_fonts:
        return _loaded_fonts[size]
    for name in _FONT_CANDIDATES:
        for cand in (name, f"{name}.ttf"):
            try:
                f = ImageFont.truetype(cand, size)
                _loaded_fonts[size] = f
                return f
            except Exception:
                pass
    f = ImageFont.load_default()
    _loaded_fonts[size] = f
    return f

def _text_size(draw: ImageDraw.ImageDraw, s: str, f: ImageFont.ImageFont) -> Tuple[int, int]:
    try:
        l, t, r, b = draw.textbbox((0, 0), s, font=f)
        return r - l, b - t
    except Exception:
        return f.getsize(s)


# ----------------------------------------------------------------------------
# Color + phase helpers
# -----------------------------------------------------------------------------
def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _lerp3(c1, c2, t):
    return tuple(int(round(_lerp(a, b, t))) for a, b in zip(c1, c2))

def _phase_from_minutes(time_minute: int) -> float:
    """Return day phase in [0,1): 0=00:00, 0.25=06:00, 0.5=12:00, 0.75=18:00."""
    return (time_minute % (24 * 60)) / (24.0 * 60.0)

def _sun_altitude(phase: float) -> float:
    """Approximate sun altitude factor in [0..1], 0 at night, 1 near noon."""
    t = (phase - 0.25) % 1.0
    return max(0.0, math.sin(math.pi * t))


# -----------------------------------------------------------------------------
#Rendering building blocks
# -----------------------------------------------------------------------------
def _draw_vertical_gradient(im: Image.Image, top_rgb, bot_rgb):
    W, H = im.size
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / max(1, H - 1)
        col = _lerp3(top_rgb, bot_rgb, t)
        d.line([(0, y), (W, y)], fill=(*col, 255))

def _sky_colors_for_phase(phase: float):
    # night (0..0.22, 0.85..1), sunrise (0.22..0.35), day (0.35..0.65), sunset (0.65..0.85)
    if phase < 0.22 or phase >= 0.85:  # night
        return (10, 15, 35), (28, 35, 70)
    if phase < 0.35:  # sunrise
        t = (phase - 0.22) / 0.13
        return _lerp3((60, 40, 80), (240, 140, 80), t), _lerp3((40, 40, 80), (120, 90, 120), t)
    if phase < 0.65:  # day
        return (125, 190, 235), (180, 225, 250)
    # sunset
    t = (phase - 0.65) / 0.20
    return _lerp3((240, 150, 90), (30, 25, 60), t), _lerp3((120, 80, 100), (25, 20, 45), t)

def _tint_color_for_phase(phase: float):
    cool_night = (20, 30, 60)      # bluish
    warm_eve   = (200, 120, 60)    # warm orange
    neutral    = (0, 0, 0)

    if phase < 0.22 or phase >= 0.85:        # night
        return (*cool_night, 110)
    if 0.65 <= phase < 0.85:                 # sunset
        t = (phase - 0.65) / 0.20
        c = _lerp3(warm_eve, cool_night, t)
        return (*c, 90)
    if 0.22 <= phase < 0.35:                 # sunrise
        t = (phase - 0.22) / 0.13
        c = _lerp3(cool_night, warm_eve, t)
        return (*c, 90)
    # day
    return (*neutral, 0)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def render_house_png(
    time_minute: int,
    *,
    size: Optional[Tuple[int, int]] = None,  # treated as a "fit box"
    with_sky: bool = True,
    show_time: bool = False,
    sharpen: bool = True,
) -> Image.Image:
    """
    Load house.png, apply time-of-day tint, and return an RGBA image.

    If `size` is provided, the result is rendered at the original resolution and then
    downscaled ONCE to FIT INSIDE the given box (preserving aspect). The sky fills
    the full canvas; the house is centered (letterboxed) on the sky.
    """
    base_house = _load_house_original()  # original RGBA
    W0, H0 = base_house.size

    # Compose at original resolution
    canvas = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))

    # Sky
    phase = _phase_from_minutes(time_minute)
    if with_sky:
        sky = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))
        top, bot = _sky_colors_for_phase(phase)
        _draw_vertical_gradient(sky, top, bot)
        canvas.alpha_composite(sky)

    # House (no scaling yet)
    canvas.alpha_composite(base_house)

    # Tint overlay
    tint_rgba = _tint_color_for_phase(phase)
    if tint_rgba[3] > 0:
        overlay = Image.new("RGBA", (W0, H0), tint_rgba)
        canvas = Image.alpha_composite(canvas, overlay)

    # Noon brightness lift
    alt = _sun_altitude(phase)
    if alt > 0.85:
        boost = int(40 * (alt - 0.85) / 0.15)  # 0..~40
        overlay = Image.new("RGBA", (W0, H0), (255, 255, 255, boost))
        canvas = Image.alpha_composite(canvas, overlay)

    # Optional time badge for demo
    if show_time:
        d = ImageDraw.Draw(canvas)
        hh = (time_minute // 60) % 24
        mm = time_minute % 60
        s = f"{hh:02d}:{mm:02d}"
        f = _font(max(14, int(H0 * 0.06)))
        tw, th = _text_size(d, s, f)
        pad_x, pad_y = 18, 12
        margin = 18
        bx0 = W0 - margin - (tw + 2 * pad_x)
        by0 = margin
        bx1 = W0 - margin
        by1 = margin + (th + 2 * pad_y)
        try:
            d.rounded_rectangle([bx0, by0, bx1, by1], radius=12, fill=(0, 0, 0, 90))
        except Exception:
            d.rectangle([bx0, by0, bx1, by1], fill=(0, 0, 0, 90))
        d.text((bx0 + pad_x + 1, by0 + pad_y + 1), s, font=f, fill=(0, 0, 0, 160))
        d.text((bx0 + pad_x,     by0 + pad_y),     s, font=f, fill=(245, 245, 245, 255))

    # Early return if no target size
    if not size:
        return canvas

    # Fit to target box (preserve aspect)
    TW, TH = size
    fitted = ImageOps.contain(canvas, (TW, TH), method=Image.LANCZOS)

    if sharpen:
        fitted = fitted.filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=2))

    out = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    ox = (TW - fitted.width) // 2
    oy = (TH - fitted.height) // 2
    out.alpha_composite(fitted, dest=(ox, oy))
    return out


# -----------------------------------------------------------------------------
# Tk demo (cycles through day → night)
# -----------------------------------------------------------------------------
def _run_demo():
    root = tk.Tk()
    root.title("House PNG – Day/Night tint demo")

    try:
        root.tk.call('tk', 'scaling', 1.0)
    except Exception:
        pass

    disp_size = (470, 280)

    lbl_img = tk.Label(root)
    lbl_img.pack(padx=8, pady=8)

    phases_hours = list(range(0, 24, 2))
    idx = {"i": 0}

    def update():
        i = idx["i"]
        hour = phases_hours[i % len(phases_hours)]
        minute = hour * 60

        img = render_house_png(minute, size=disp_size, with_sky=True, show_time=True, sharpen=True)
        tk_img = ImageTk.PhotoImage(img)
        lbl_img.configure(image=tk_img)
        lbl_img.image = tk_img

        idx["i"] = i + 1
        root.after(1000, update)

    update()
    root.mainloop()


if __name__ == "__main__":
    _run_demo()
