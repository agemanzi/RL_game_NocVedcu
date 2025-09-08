# src/thermal_toy/gui/sprite_factory.py
from __future__ import annotations
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageTk
from .assets import load_sprite  # already present
from .assets import _candidate_dirs  # to help locate asset manually


# ---------- helpers ----------
def _font(big: bool = False):
    size = 56 if big else 28
    for name in ("Segoe UI Semibold", "Segoe UI", "Arial", "DejaVuSans"):
        # try with and without .ttf
        for candidate in (name, name + ".ttf"):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    return ImageFont.load_default()

def _rounded_panel(size: Tuple[int, int], bg: Tuple[int, int, int], radius: int = 24):
    w, h = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    try:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=bg, outline=(255, 255, 255, 160), width=3)
    except Exception:
        d.rectangle([0, 0, w - 1, h - 1], fill=bg, outline=(255, 255, 255, 160), width=3)
    return im, d

def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    """Pillow 10+ compatible text measure."""
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except Exception:
        try:
            return font.getsize(text)  # older Pillow fallback
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

# ---------- sprites ----------
@lru_cache(maxsize=256)
def sprite_pv(on: bool, size: Tuple[int, int] = (200, 200)) -> ImageTk.PhotoImage:
    bg = PALETTE.green if on else PALETTE.gray
    im, d = _rounded_panel(size, bg)
    w, h = size
    f_big = _font(True)

    # sun
    sun_cx, sun_cy, sun_r = int(w * 0.28), int(h * 0.28), int(min(w, h) * 0.12)
    d.ellipse([sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r], fill=(255, 240, 150, 240))
    for a in range(0, 360, 30):
        dx = int(sun_r * 1.6 * math.cos(math.radians(a)))
        dy = int(sun_r * 1.6 * math.sin(math.radians(a)))
        d.line([(sun_cx, sun_cy), (sun_cx + dx, sun_cy + dy)], fill=(255, 240, 150, 220), width=3)

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
        filled = int(bar_w * _clamp01(abs(u)))
        d.rounded_rectangle([pad, y0, pad + filled, y0 + bar_h], radius=10, fill=(255, 255, 255, 220))
    except Exception:
        d.rectangle([pad, y0, pad + bar_w, y0 + bar_h], fill=(255, 255, 255, 60))
        filled = int(bar_w * _clamp01(abs(u)))
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

# src/thermal_toy/gui/sprite_factory.py
@lru_cache(maxsize=256)
def sprite_house_with_temp(
    sprite_name: str,
    tin_c: float,
    tout_c: float,
    size: Tuple[int, int] = (460, 260),
    lines: tuple | list | None = None,   # <- NEW
) -> ImageTk.PhotoImage:
    """Overlay status (top-left) and Tin/Tout (bottom-right) on house image."""
    stem = sprite_name if sprite_name.lower().endswith(".png") else f"{sprite_name}.png"
    sprite_path = None
    for base in _candidate_dirs():
        p = base / stem
        if p.exists():
            sprite_path = p
            break
    if sprite_path is None:
        raise FileNotFoundError(f"Could not find sprite '{sprite_name}' in any asset directory.")

    img = Image.open(sprite_path).convert("RGBA").resize(size)
    draw = ImageDraw.Draw(img)
    font = _font(False)
    w, h = size
    pad = 12

    # --- top-left multi-line overlay (NEW) ---
    if lines:
        # measure
        maxw = 0; totalh = 0; gap = 4
        sizes = []
        for s in lines:
            tw, th = _text_size(draw, str(s), font)
            sizes.append((tw, th))
            maxw = max(maxw, tw)
            totalh += th + gap
        totalh -= gap
        box_w = maxw + 2*pad
        box_h = totalh + 2*pad
        draw.rectangle([pad, pad, pad + box_w, pad + box_h], fill=(0, 0, 0, 150))
        y = pad + (box_h - 2*pad - totalh) // 2
        for (s, (tw, th)) in zip(lines, sizes):
            draw.text((pad + (box_w - 2*pad - tw)//2 + pad//2, y), str(s), font=font, fill=(255, 255, 255, 230))
            y += th + gap

    # --- bottom-right Tin/Tout box (kept) ---
    labels = [f"Tin: {tin_c:.1f}°C", f"Tout: {tout_c:.1f}°C"]
    sizes2 = [_text_size(draw, lab, font) for lab in labels]
    tw_max = max(tw for tw, _ in sizes2)
    th_sum = sum(th for _, th in sizes2) + 6
    bx_w = tw_max + 2*pad; bx_h = th_sum + 2*pad
    bx_x1 = w - bx_w - pad; bx_y1 = h - bx_h - pad
    draw.rectangle([bx_x1, bx_y1, bx_x1 + bx_w, bx_y1 + bx_h], fill=(0, 0, 0, 140))
    y = bx_y1 + pad
    for (lab, (tw, th)) in zip(labels, sizes2):
        draw.text((bx_x1 + (bx_w - tw)//2, y), lab, font=font, fill=(255, 255, 255, 255))
        y += th + 6

    return ImageTk.PhotoImage(img)