from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple, Iterable

from PIL import Image, ImageDraw, ImageFont, ImageTk

# Import the image renderer; we wrap it to return a Tk PhotoImage
from .house_spline_runtime import render_house_png

__all__ = ["sprite_pv", "sprite_hvac", "sprite_battery", "sprite_house_from_png"]


# ---------- helpers ----------
def _font(big: bool = False):
    size = 56 if big else 28
    for name in ("Segoe UI Semibold", "Segoe UI", "Arial", "DejaVuSans"):
        for candidate in (name, name + ".ttf"):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    return ImageFont.load_default()

def _font_px(px: int) -> ImageFont.ImageFont:
    for name in ("Segoe UI", "SegoeUI", "Arial", "DejaVuSansMono", "DejaVuSans"):
        for cand in (name, f"{name}.ttf"):
            try:
                return ImageFont.truetype(cand, px)
            except Exception:
                pass
    return ImageFont.load_default()

def _rounded_panel(size: Tuple[int, int], bg: Tuple[int, int, int], radius: int = 24):
    w, h = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    try:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius,
                            fill=bg, outline=(255, 255, 255, 160), width=3)
    except Exception:
        d.rectangle([0, 0, w - 1, h - 1], fill=bg, outline=(255, 255, 255, 160), width=3)
    return im, d

def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except Exception:
        try:
            return font.getsize(text)
        except Exception:
            return (len(text) * 8, 16)

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# ---------- palette ----------
@dataclass(frozen=True)
class Palette:
    red   = (220, 70, 50)
    amber = (245, 185, 70)
    green = (46, 204, 113)
    blue  = (58, 123, 227)
    gray  = (95, 95, 95)
    dark  = (60, 70, 100)

PALETTE = Palette()


# ---------- device sprites ----------
@lru_cache(maxsize=256)
def sprite_pv(on: bool, size: Tuple[int, int] = (200, 200)) -> ImageTk.PhotoImage:
    bg = PALETTE.green if on else PALETTE.gray
    im, d = _rounded_panel(size, bg)
    w, h = size
    f_big = _font(True)

    # sun
    sun_cx, sun_cy, sun_r = int(w * 0.28), int(h * 0.28), int(min(w, h) * 0.12)
    d.ellipse([sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r],
              fill=(255, 240, 150, 240))
    for a in range(0, 360, 30):
        dx = int(sun_r * 1.6 * math.cos(math.radians(a)))
        dy = int(sun_r * 1.6 * math.sin(math.radians(a)))
        d.line([(sun_cx, sun_cy), (sun_cx + dx, sun_cy + dy)],
               fill=(255, 240, 150, 220), width=3)

    # panel
    pad = 18
    d.rectangle([pad, h - int(h * 0.40), w - pad, h - pad], fill=(20, 50, 80, 220))
    for i in range(1, 4):
        x = pad + i * (w - 2 * pad) / 4
        d.line([(x, h - int(h * 0.40)), (x, h - pad)], fill=(255, 255, 255, 90), width=2)
    for j in range(1, 3):
        y = h - int(h * 0.40) + j * ((int(h * 0.40) - pad) / 3)
        d.line([(pad, y), (w - pad, y)], fill=(255, 255, 255, 90), width=2)

    text = "PV ON" if on else "PV OFF"
    tw, th = _text_size(d, text, f_big)
    d.text(((w - tw) // 2, int(h * 0.02)), text, fill=(255, 255, 255, 255), font=f_big)
    return ImageTk.PhotoImage(im)


@lru_cache(maxsize=256)
def sprite_hvac(u_bidir: float, size: Tuple[int, int] = (200, 200)) -> ImageTk.PhotoImage:
    u = max(-1.0, min(1.0, float(u_bidir)))
    heating = u > 0
    bg = PALETTE.red if heating else (PALETTE.blue if u < 0 else PALETTE.gray)
    im, d = _rounded_panel(size, bg)
    w, h = size
    f_big = _font(True)
    f = _font(False)

    pct = int(round(abs(u) * 100))
    mode = "HEAT" if heating else ("COOL" if u < 0 else "IDLE")
    title = f"HVAC {('+' if heating else ('-' if u < 0 else '±'))}{pct}%"
    tw, th = _text_size(d, title, f_big)
    d.text(((w - tw) // 2, 12), title, fill=(255, 255, 255, 255), font=f_big)
    mw, mh = _text_size(d, mode, f)
    d.text(((w - mw) // 2, 16 + th), mode, fill=(255, 255, 255, 210), font=f)

    pad = 18
    bar_w = w - 2 * pad
    bar_h = 22
    y0 = h - pad - bar_h
    try:
        d.rounded_rectangle([pad, y0, pad + bar_w, y0 + bar_h], radius=10, fill=(255, 255, 255, 60))
        filled = int(bar_w * abs(u))
        d.rounded_rectangle([pad, y0, pad + filled, y0 + bar_h], radius=10, fill=(255, 255, 255, 220))
    except Exception:
        d.rectangle([pad, y0, pad + bar_w, y0 + bar_h], fill=(255, 255, 255, 60))
        filled = int(bar_w * abs(u))
        d.rectangle([pad, y0, pad + filled, y0 + bar_h], fill=(255, 255, 255, 220))
    return ImageTk.PhotoImage(im)


@lru_cache(maxsize=256)
def sprite_battery(soc01: float, size: Tuple[int, int] = (200, 200)) -> ImageTk.PhotoImage:
    s = _clamp01(soc01)
    if s < 0.5:
        t = s / 0.5
        col = tuple(int((1 - t) * PALETTE.red[i] + t * PALETTE.amber[i]) for i in range(3))
    else:
        t = (s - 0.5) / 0.5
        col = tuple(int((1 - t) * PALETTE.amber[i] + t * PALETTE.green[i]) for i in range(3))
    im, d = _rounded_panel(size, col)
    w, h = size
    f_big = _font(True)
    f = _font(False)

    title = "BATTERY"
    tw, th = _text_size(d, title, f_big)
    d.text(((w - tw) // 2, 12), title, fill=(255, 255, 255, 255), font=f_big)

    bw, bh = int(w * 0.72), int(h * 0.34)
    x0, y0 = (w - bw) // 2, int(h * 0.40)
    cap = int(bw * 0.06)
    try:
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=12,
                            outline=(255, 255, 255, 210), width=3, fill=(0, 0, 0, 30))
    except Exception:
        d.rectangle([x0, y0, x0 + bw, y0 + bh], outline=(255, 255, 255, 210),
                    width=3, fill=(0, 0, 0, 30))
    d.rectangle([x0 + bw + 4, y0 + bh * 0.30, x0 + bw + 4 + cap, y0 + bh * 0.70],
                fill=(255, 255, 255, 210))

    pad = 8
    inner_w = bw - 2 * pad
    inner_h = bh - 2 * pad
    fill_w = int(inner_w * s)
    d.rectangle([x0 + pad, y0 + pad, x0 + pad + fill_w, y0 + pad + inner_h],
                fill=(255, 255, 255, 220))

    pct = f"{int(round(100 * s))}%"
    pw, ph = _text_size(d, pct, f)
    d.text((x0 + (bw - pw) // 2, y0 + (bh - ph) // 2), pct, fill=(0, 0, 0, 230), font=f)
    return ImageTk.PhotoImage(im)


# ---------- house sprite wrapper ----------
def sprite_house_from_png(
    *,
    time_minute: int,
    tin_c: float,
    tout_c: float,
    size: Tuple[int, int],
    lines: Iterable[str] = (),
    with_sky: bool = True,
) -> ImageTk.PhotoImage:
    """
    Render the tinted house PNG via render_house_png(...), overlay Tin/Tout + lines,
    and return a Tk PhotoImage.
    """
    im = render_house_png(
        time_minute,
        size=size,
        with_sky=with_sky,
        show_time=False,
        sharpen=True,
    ).copy()

    d = ImageDraw.Draw(im)
    W, H = im.size
    f_head = _font_px(max(12, int(H * 0.045)))
    f_line = _font_px(max(11, int(H * 0.040)))

    header = f"Tin {tin_c:.1f}°C   Tout {tout_c:.1f}°C"

    # measure multi-line box
    pad_x, pad_y = 10, 8
    gap = 4
    lines_list = [header] + list(lines)
    widths, heights = [], []
    for s in lines_list:
        w, h = _text_size(d, s, f_head if s is header else f_line)
        widths.append(w); heights.append(h)

    box_w = max(widths) + 2 * pad_x
    box_h = (sum(heights) + (len(lines_list) - 1) * gap) + 2 * pad_y

    # bottom-left placement
    bx0 = 10
    by0 = H - 10 - box_h
    bx1 = bx0 + box_w
    by1 = by0 + box_h

    # backdrop
    try:
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=10, fill=(0, 0, 0, 90))
    except Exception:
        d.rectangle([bx0, by0, bx1, by1], fill=(0, 0, 0, 90))

    # draw lines
    y = by0 + pad_y
    d.text((bx0 + pad_x, y), header, fill=(245, 245, 245, 255), font=f_head)
    y += heights[0] + gap
    for i, s in enumerate(lines_list[1:], start=1):
        d.text((bx0 + pad_x, y), s, fill=(235, 235, 235, 230), font=f_line)
        y += heights[i] + gap

    return ImageTk.PhotoImage(im)
