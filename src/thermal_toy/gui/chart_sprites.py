from __future__ import annotations
import math
from typing import Sequence, Tuple, Optional, List
from PIL import Image, ImageDraw, ImageFont, ImageTk


# ------- text + styling helpers -------
def _font(size: int = 12):
    for name in ("Segoe UI", "Arial", "DejaVuSans"):
        for cand in (name, name + ".ttf"):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                pass
    return ImageFont.load_default()

def _text_size(d: ImageDraw.ImageDraw, s: str, f) -> Tuple[int, int]:
    try:
        l, t, r, b = d.textbbox((0, 0), s, font=f)
        return r - l, b - t
    except Exception:
        try:
            return f.getsize(s)
        except Exception:
            return (len(s) * 7, 12)

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ------- axes + mapping -------
def _auto_minmax(vals: Sequence[float], pad_ratio: float = 0.08, fallback=(0.0, 1.0)) -> Tuple[float, float]:
    xs = [float(v) for v in vals if math.isfinite(v)]
    if not xs:
        return fallback
    lo, hi = min(xs), max(xs)
    if lo == hi:
        lo -= 1.0
        hi += 1.0
    pad = (hi - lo) * pad_ratio
    return lo - pad, hi + pad

def _xmap(x: float, xmin: float, xmax: float, L: int, R: int) -> int:
    if xmax == xmin:
        return L
    t = (x - xmin) / (xmax - xmin)
    return int(round(L + t * (R - L)))

def _ymap(y: float, ymin: float, ymax: float, T: int, B: int) -> int:
    if ymax == ymin:
        return B
    t = (y - ymin) / (ymax - ymin)
    return int(round(B - t * (B - T)))  # invert y (top-down)

def _draw_axes(d: ImageDraw.ImageDraw, rect: Tuple[int, int, int, int], *,
               xticks: Sequence[float], xmin: float, xmax: float,
               yticks: Sequence[float], ymin: float, ymax: float,
               label_left: Optional[str] = None, label_right: Optional[str] = None):
    L, T, R, B = rect
    # frame
    d.rectangle([L, T, R, B], outline=(180, 180, 180, 255), width=1)
    f_tick = _font(11)
    # x ticks
    for xv in xticks:
        x = _xmap(xv, xmin, xmax, L, R)
        d.line([(x, B), (x, B + 4)], fill=(150, 150, 150, 255), width=1)
        lab = f"{xv:g}"
        w, h = _text_size(d, lab, f_tick)
        d.text((x - w // 2, B + 6), lab, fill=(80, 80, 80, 255), font=f_tick)
    # y ticks (left)
    for yv in yticks:
        y = _ymap(yv, ymin, ymax, T, B)
        d.line([(L - 4, y), (L, y)], fill=(150, 150, 150, 255), width=1)
        lab = f"{yv:g}"
        w, h = _text_size(d, lab, f_tick)
        d.text((L - 8 - w, y - h // 2), lab, fill=(80, 80, 80, 255), font=f_tick)
    # labels
    f_lbl = _font(12)
    if label_left:
        w, h = _text_size(d, label_left, f_lbl)
        d.text((L, T - h - 2), label_left, fill=(70, 70, 70, 255), font=f_lbl)
    if label_right:
        w, h = _text_size(d, label_right, f_lbl)
        d.text((R - w, T - h - 2), label_right, fill=(70, 70, 70, 255), font=f_lbl)

def _ticks_lin(lo: float, hi: float, step: float) -> List[float]:
    if step <= 0 or hi <= lo:
        return []
    # start on a multiple of step
    start = math.ceil(lo / step) * step
    xs = []
    x = start
    # small epsilon to avoid float rounding misses
    while x <= hi + 1e-9:
        xs.append(round(x, 6))
        x += step
    return xs


# ------- chart sprite generators -------
def make_temp_chart_sprite(
    hours: Sequence[float],
    tin_hist: Sequence[float],
    comfort_L: float,
    comfort_U: float,
    *,
    size: Tuple[int, int] = (860, 180),
    cursor_hour: Optional[float] = None,
) -> ImageTk.PhotoImage:
    W, H = size
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    # plot rect
    L, T, R, B = 50, 22, W - 12, H - 30

    # x-range and ticks (hours)
    if len(hours) == 0:
        return ImageTk.PhotoImage(im)
    xmin, xmax = float(hours[0]), float(hours[-1])
    xt = _ticks_lin(0.0, 24.0, 4.0) if (xmax - xmin) >= 12 else _ticks_lin(xmin, xmax, max(1.0, (xmax - xmin) / 6))

    # y-range from comfort + data
    vals = list(tin_hist) + [comfort_L, comfort_U]
    ymin, ymax = _auto_minmax(vals, pad_ratio=0.15, fallback=(comfort_L - 2, comfort_U + 2))
    yt = _ticks_lin(math.floor(ymin), math.ceil(ymax), 2.0)

    # comfort band
    yL = _ymap(comfort_L, ymin, ymax, T, B)
    yU = _ymap(comfort_U, ymin, ymax, T, B)
    d.rectangle([L, yU, R, yL], fill=(120, 200, 120, 40), outline=None)
    d.line([(L, yL), (R, yL)], fill=(80, 160, 80, 180), width=1)
    d.line([(L, yU), (R, yU)], fill=(80, 160, 80, 180), width=1)

    # Tin line
    if len(tin_hist) > 0:
        xs = [_xmap(h, xmin, xmax, L, R) for h in hours[:len(tin_hist)]]
        ys = [_ymap(v, ymin, ymax, T, B) for v in tin_hist]
        for i in range(1, len(xs)):
            d.line([(xs[i - 1], ys[i - 1]), (xs[i], ys[i])], fill=(30, 30, 30, 255), width=2)

    # axes and ticks
    _draw_axes(
        d, (L, T, R, B),
        xticks=xt, xmin=xmin, xmax=xmax,
        yticks=yt, ymin=ymin, ymax=ymax,
        label_left="Tin (°C)"
    )

    # cursor
    if cursor_hour is not None:
        cx = _xmap(cursor_hour, xmin, xmax, L, R)
        d.line([(cx, T), (cx, B)], fill=(0, 0, 0, 160), width=1)

    return ImageTk.PhotoImage(im)


def make_price_chart_sprite(
    hours: Sequence[float],
    price: Sequence[float],
    *,
    size: Tuple[int, int] = (860, 140),
    cursor_hour: Optional[float] = None,
) -> ImageTk.PhotoImage:
    W, H = size
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    L, T, R, B = 50, 18, W - 12, H - 28

    if len(hours) == 0:
        return ImageTk.PhotoImage(im)
    xmin, xmax = float(hours[0]), float(hours[-1])
    ymin, ymax = _auto_minmax(price, pad_ratio=0.12, fallback=(0.0, 1.0))
    xt = _ticks_lin(0.0, 24.0, 4.0)
    # price ticks rounded to 0.05
    p_step = max(0.05, (ymax - ymin) / 5.0)
    p_step = round(p_step / 0.05) * 0.05
    yt = _ticks_lin(math.floor(ymin / p_step) * p_step, math.ceil(ymax / p_step) * p_step, p_step)

    # price line
    if len(price) > 0:
        xs = [_xmap(h, xmin, xmax, L, R) for h in hours]
        ys = [_ymap(v, ymin, ymax, T, B) for v in price]
        for i in range(1, len(xs)):
            d.line([(xs[i - 1], ys[i - 1]), (xs[i], ys[i])], fill=(60, 120, 220, 255), width=2)

    _draw_axes(
        d, (L, T, R, B),
        xticks=xt, xmin=xmin, xmax=xmax,
        yticks=yt, ymin=ymin, ymax=ymax,
        label_left="Price (€/kWh)"
    )

    if cursor_hour is not None:
        cx = _xmap(cursor_hour, xmin, xmax, L, R)
        d.line([(cx, T), (cx, B)], fill=(0, 0, 0, 160), width=1)

    return ImageTk.PhotoImage(im)


def make_weather_pv_chart_sprite(
    hours: Sequence[float],
    tout: Sequence[float],
    pv: Sequence[float],
    *,
    size: Tuple[int, int] = (860, 180),
    cursor_hour: Optional[float] = None,
) -> ImageTk.PhotoImage:
    W, H = size
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    L, T, R, B = 50, 22, W - 50, H - 30  # leave room right for PV label

    if len(hours) == 0:
        return ImageTk.PhotoImage(im)
    xmin, xmax = float(hours[0]), float(hours[-1])

    # left axis: Tout
    yLmin, yLmax = _auto_minmax(tout, pad_ratio=0.12, fallback=(-5.0, 30.0))
    ytL = _ticks_lin(math.floor(yLmin), math.ceil(yLmax), 5.0)

    # right axis (PV)
    pvmax = max([0.0] + [float(v) for v in pv if math.isfinite(v)])
    yRmin, yRmax = 0.0, max(0.1, pvmax * 1.10)
    ytR = _ticks_lin(yRmin, yRmax, max(0.2, yRmax / 5.0))

    xt = _ticks_lin(0.0, 24.0, 4.0)

    # PV area (right axis scaled into same pixel rect)
    def ymapR(v: float) -> int:
        return _ymap(v, yRmin, yRmax, T, B)
    xs = [_xmap(h, xmin, xmax, L, R) for h in hours]
    ys_pv = [ymapR(v) for v in pv]
    if len(xs) >= 2:
        poly = [(xs[0], B)] + list(zip(xs, ys_pv)) + [(xs[-1], B)]
        d.polygon(poly, fill=(255, 200, 100, 90))

    # Tout line (left axis)
    ys_t = [_ymap(v, yLmin, yLmax, T, B) for v in tout]
    for i in range(1, len(xs)):
        d.line([(xs[i - 1], ys_t[i - 1]), (xs[i], ys_t[i])], fill=(40, 40, 40, 255), width=2)

    # axes (left y and bottom x)
    _draw_axes(
        d, (L, T, R, B),
        xticks=xt, xmin=xmin, xmax=xmax,
        yticks=ytL, ymin=yLmin, ymax=yLmax,
        label_left="Tout (°C)", label_right=None
    )

    # right y-axis ticks for PV
    f_tick = _font(11)
    for yv in ytR:
        y = _ymap(yv, yRmin, yRmax, T, B)
        d.line([(R, y), (R + 4, y)], fill=(150, 150, 150, 255), width=1)
        lab = f"{yv:g}"
        w, h = _text_size(d, lab, f_tick)
        d.text((R + 6, y - h // 2), lab, fill=(80, 80, 80, 255), font=f_tick)
    f_lbl = _font(12)
    lbl = "PV (per kWp)"
    w, h = _text_size(d, lbl, f_lbl)
    d.text((W - w - 8, T - h - 2), lbl, fill=(70, 70, 70, 255), font=f_lbl)

    if cursor_hour is not None:
        cx = _xmap(cursor_hour, xmin, xmax, L, R)
        d.line([(cx, T), (cx, B)], fill=(0, 0, 0, 160), width=1)

    return ImageTk.PhotoImage(im)
