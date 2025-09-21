# output_splines.py
from __future__ import annotations

import math
from typing import Sequence, Tuple, Optional, List

from PIL import Image, ImageDraw, ImageFont, ImageTk


# =========================
# text + styling helpers
# =========================
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


# =========================
# axes + mapping
# =========================
def _auto_minmax(vals: Sequence[float], pad_ratio: float = 0.08,
                 fallback=(0.0, 1.0)) -> Tuple[float, float]:
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


def _ticks_lin(lo: float, hi: float, step: float) -> List[float]:
    if step <= 0 or hi <= lo:
        return []
    start = math.ceil(lo / step) * step
    xs = []
    x = start
    while x <= hi + 1e-9:
        xs.append(round(x, 6))
        x += step
    return xs


def _draw_axes(d: ImageDraw.ImageDraw, rect: Tuple[int, int, int, int], *,
               xticks: Sequence[float], xmin: float, xmax: float,
               yticks: Sequence[float], ymin: float, ymax: float,
               label_left: Optional[str] = None, label_right: Optional[str] = None,
               outline: Optional[Tuple[int, int, int, int]] = None):
    L, T, R, B = rect
    if outline is not None:
        d.rectangle([L, T, R, B], outline=outline, width=1)
    f_tick = _font(11)
    # x ticks
    for xv in xticks:
        x = _xmap(xv, xmin, xmax, L, R)
        d.line([(x, B), (x, B + 4)], fill=(150, 150, 150, 255), width=1)
        lab = f"{xv:g}"
        w, h = _text_size(d, lab, f_tick)
        d.text((x - w // 2, B + 6), lab, fill=(80, 80, 80, 255), font=f_tick)
    # y ticks
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


# =========================
# drawing primitives
# =========================
def _polyline(d: ImageDraw.ImageDraw, xs: List[int], ys: List[int], color, width=2):
    for i in range(1, len(xs)):
        d.line([(xs[i - 1], ys[i - 1]), (xs[i], ys[i])], fill=color, width=width)


def _area(d: ImageDraw.ImageDraw, xs: List[int], ys: List[int], y_base: int, fill):
    if len(xs) < 2:
        return
    poly = [(xs[0], y_base)] + list(zip(xs, ys)) + [(xs[-1], y_base)]
    d.polygon(poly, fill=fill)


# =========================
# 1) Energy breakdown
# =========================
def make_energy_breakdown_sprite(
    *,
    hours: Sequence[float],
    people_kw: Sequence[float],
    hvac_kw: Sequence[float],
    battery_kw: Sequence[float],
    pv_kw: Sequence[float],
    size: Tuple[int, int] = (860, 180),
    cursor_hour: Optional[float] = None,
    margins: Tuple[int, int, int, int] = (16, 12, 16, 16),
    outer_pad: Tuple[int, int, int, int] = (8, 8, 8, 8),
) -> ImageTk.PhotoImage:
    W, H = size
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)

    # Outer panel
    pL, pT, pR, pB = outer_pad
    PL, PT, PR, PB = pL, pT, W - pR, H - pB
    d.rectangle([PL, PT, PR, PB], fill=(255, 255, 255, 255))

    # Axes rect
    mL, mT, mR, mB = margins
    L, T, R, B = PL + mL, PT + mT, PR - mR, PB - mB
    Li, Ti, Ri, Bi = L + 1, T + 1, R - 1, B - 1

    if not hours:
        return ImageTk.PhotoImage(im)

    xmin, xmax = float(hours[0]), float(hours[-1])

    # Build numeric series
    n = len(hours)
    # Pad/clip component arrays to length n
    def pad(a):
        a = list(a)[:n]
        if len(a) < n:
            a += [0.0] * (n - len(a))
        return a

    p  = pad(people_kw)
    h  = pad(hvac_kw)
    b  = pad(battery_kw)       # can be +/- (discharge positive or whichever convention you want)
    pv = pad(pv_kw)            # >= 0, subtracts from demand

    # Net = people + hvac + battery - pv
    net = [p[i] + h[i] + b[i] - pv[i] for i in range(n)]

    # y-range that captures everything (a little pad)
    def _minmax(xs):
        xs = [float(v) for v in xs if math.isfinite(v)]
        return (0.0, 1.0) if not xs else (min(xs), max(xs))
    lo = min(_minmax(net)[0], 0.0, _minmax(b)[0] - _minmax(pv)[1])
    hi = max(_minmax(net)[1], _minmax(p)[1] + _minmax(h)[1] + max(0.0, _minmax(b)[1]))
    if hi == lo:
        hi += 1.0
        lo -= 1.0
    pad = (hi - lo) * 0.08
    ymin, ymax = lo - pad, hi + pad

    # Mapping
    xs = [_xmap(hh, xmin, xmax, Li, Ri) for hh in hours]
    def ymap(v: float) -> int:
        return _ymap(v, ymin, ymax, Ti, Bi)

    # Screen-space Y lists
    people_y = [ymap(v) for v in p]
    hvac_y   = [ymap(v) for v in h]
    batt_y   = [ymap(v) for v in b]           # can go above/below Bi
    pv_y     = [ymap(-v) for v in pv]         # draw as negative area (below baseline)
    net_y    = [ymap(v) for v in net]

    # Filled components (baseline at Bi!)
    # people
    _area(d, xs, people_y, Bi, fill=(150, 180, 150, 110))
    # hvac
    _area(d, xs, hvac_y,   Bi, fill=(160, 200, 240, 110))
    # battery positive/negative as two semi-transparent fills
    batt_pos_y = [ymap(max(0.0, bb)) for bb in b]
    batt_neg_y = [ymap(min(0.0, bb)) for bb in b]
    _area(d, xs, batt_pos_y, Bi, fill=(230, 180, 80, 110))
    _area(d, xs, batt_neg_y, Bi, fill=(230, 150, 60, 110))
    # PV (as negative contribution below baseline)
    _area(d, xs, pv_y, Bi, fill=(200, 170, 110, 90))

    # Net line on top
    for i in range(1, n):
        d.line([(xs[i-1], net_y[i-1]), (xs[i], net_y[i])], fill=(30, 30, 30, 255), width=2)

    # Axes ticks/labels
    xt = _ticks_lin(0.0, 24.0, 4.0)
    # simple symmetric y ticks around 0 if range crosses 0, otherwise regular
    if ymin < 0 < ymax:
        span = max(abs(ymin), abs(ymax))
        step = max(0.5, span / 5.0)
        yt_vals = _ticks_lin(-math.ceil(span/step)*step, math.ceil(span/step)*step, step)
    else:
        step = max(0.5, (ymax - ymin) / 5.0)
        yt_vals = _ticks_lin(math.floor(ymin/step)*step, math.ceil(ymax/step)*step, step)

    _draw_axes(d, (L, T, R, B),
               xticks=xt, xmin=xmin, xmax=xmax,
               yticks=yt_vals, ymin=ymin, ymax=ymax,
               label_left="Power (kW)")

    # cursor
    if cursor_hour is not None:
        cx = _xmap(cursor_hour, xmin, xmax, Li, Ri)
        d.line([(cx, Ti), (cx, Bi)], fill=(0, 0, 0, 160), width=1)

    return ImageTk.PhotoImage(im)



# =========================
# 2) Actions (controls)
# =========================
def make_actions_sprite(
    *,
    hours: Sequence[float],
    u_hvac: Sequence[float],   # [-1, 1]
    u_batt: Sequence[float],   # [-1, 1]
    size: Tuple[int, int] = (470, 180),
    cursor_hour: Optional[float] = None,
    margins: Tuple[int, int, int, int] = (16, 12, 16, 16),
    outer_pad: Tuple[int, int, int, int] = (8, 8, 8, 8),
) -> ImageTk.PhotoImage:
    W, H = size
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)

    pL, pT, pR, pB = outer_pad
    PL, PT, PR, PB = pL, pT, W - pR, H - pB
    d.rectangle([PL, PT, PR, PB], outline=None, fill=(255, 255, 255, 255))

    mL, mT, mR, mB = margins
    L, T, R, B = PL + mL, PT + mT, PR - mR, PB - mB
    Li, Ti, Ri, Bi = L + 1, T + 1, R - 1, B - 1

    if not hours:
        return ImageTk.PhotoImage(im)

    xmin, xmax = float(hours[0]), float(hours[-1])
    xt = _ticks_lin(0.0, 24.0, 4.0)

    n = min(len(hours), len(u_hvac), len(u_batt))
    hours = hours[:n]
    uh = [max(-1.0, min(1.0, float(u_hvac[i]))) for i in range(n)]
    ub = [max(-1.0, min(1.0, float(u_batt[i]))) for i in range(n)]

    ymin, ymax = -1.0, 1.0
    yt = _ticks_lin(-1.0, 1.0, 0.5)

    xs = [_xmap(hh, xmin, xmax, Li, Ri) for hh in hours]
    y0 = _ymap(0.0, ymin, ymax, Ti, Bi)
    # faint baseline
    d.line([(Li, y0), (Ri, y0)], fill=(180, 180, 180, 180), width=1)

    yh = [_ymap(uh[i], ymin, ymax, Ti, Bi) for i in range(n)]
    yb = [_ymap(ub[i], ymin, ymax, Ti, Bi) for i in range(n)]

    _polyline(d, xs, yh, color=(40, 120, 40, 255), width=2)    # HVAC control
    _polyline(d, xs, yb, color=(160, 60, 200, 255), width=2)   # Battery control

    _draw_axes(d, (L, T, R, B),
               xticks=xt, xmin=xmin, xmax=xmax,
               yticks=yt, ymin=ymin, ymax=ymax,
               label_left="Actions (u)", label_right=None,
               outline=None)

    if cursor_hour is not None:
        cx = _xmap(cursor_hour, xmin, xmax, Li, Ri)
        d.line([(cx, Ti), (cx, Bi)], fill=(0, 0, 0, 140), width=1)

    return ImageTk.PhotoImage(im)

def _area(d: ImageDraw.ImageDraw, xs, ys, base_y: int, *, fill):
    """
    Filled area between the polyline (xs, ys) and a horizontal baseline
    at screen y = base_y.  Coordinates must be integers for PIL.
    """
    if not xs or not ys:
        return
    n = min(len(xs), len(ys))
    bx = int(xs[0])
    ex = int(xs[n - 1])
    pts = [(bx, int(base_y))] + [(int(xs[i]), int(ys[i])) for i in range(n)] + [(ex, int(base_y))]
    d.polygon(pts, fill=fill)

# =========================
# 3) Immediate rewards (costs)
# =========================
def make_rewards_sprite(
    *,
    hours: Sequence[float],
    opex_eur_step: Sequence[float],          # >= 0 per step
    comfort_penalty_eur_step: Sequence[float],  # >= 0 per step
    size: Tuple[int, int] = (470, 180),
    cursor_hour: Optional[float] = None,
    margins: Tuple[int, int, int, int] = (16, 12, 16, 16),
    outer_pad: Tuple[int, int, int, int] = (8, 8, 8, 8),
) -> ImageTk.PhotoImage:
    """
    Stacked areas for OPEX and Comfort Penalty (both positive),
    plus a thin line for their sum. If your environment uses reward = -(opex + penalty),
    this makes the contributors visually clear.
    """
    W, H = size
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)

    pL, pT, pR, pB = outer_pad
    PL, PT, PR, PB = pL, pT, W - pR, H - pB
    d.rectangle([PL, PT, PR, PB], outline=None, fill=(255, 255, 255, 255))

    mL, mT, mR, mB = margins
    L, T, R, B = PL + mL, PT + mT, PR - mR, PB - mB
    Li, Ti, Ri, Bi = L + 1, T + 1, R - 1, B - 1

    if not hours:
        return ImageTk.PhotoImage(im)

    xmin, xmax = float(hours[0]), float(hours[-1])
    xt = _ticks_lin(0.0, 24.0, 4.0)

    n = min(len(hours), len(opex_eur_step), len(comfort_penalty_eur_step))
    hours = hours[:n]
    opex = [max(0.0, float(opex_eur_step[i])) for i in range(n)]
    pen  = [max(0.0, float(comfort_penalty_eur_step[i])) for i in range(n)]
    total = [opex[i] + pen[i] for i in range(n)]

    ymin, ymax = _auto_minmax(total, pad_ratio=0.15, fallback=(0.0, 1.0))
    ymin = min(0.0, ymin)   # keep baseline at 0 or below
    step = max(0.05, (ymax - ymin) / 5.0)
    step = round(step / 0.05) * 0.05
    yt = _ticks_lin(math.floor(ymin / step) * step, math.ceil(ymax / step) * step, step)

    xs = [_xmap(hh, xmin, xmax, Li, Ri) for hh in hours]
    y0 = _ymap(0.0, ymin, ymax, Ti, Bi)

    # Stack OPEX then Penalty (both from baseline for simplicity/clarity)
    y_opex = [_ymap(opex[i], ymin, ymax, Ti, Bi) for i in range(n)]
    _area(d, xs, y_opex, y0, fill=(80, 140, 210, 90))      # blue-ish

    y_pen = [_ymap(pen[i], ymin, ymax, Ti, Bi) for i in range(n)]
    _area(d, xs, y_pen, y0, fill=(210, 120, 120, 90))      # red-ish

    # total line
    y_total = [_ymap(total[i], ymin, ymax, Ti, Bi) for i in range(n)]
    _polyline(d, xs, y_total, color=(30, 30, 30, 255), width=2)

    _draw_axes(d, (L, T, R, B),
               xticks=xt, xmin=xmin, xmax=xmax,
               yticks=yt, ymin=ymin, ymax=ymax,
               label_left="€ per step", label_right=None,
               outline=None)

    if cursor_hour is not None:
        cx = _xmap(cursor_hour, xmin, xmax, Li, Ri)
        d.line([(cx, Ti), (cx, Bi)], fill=(0, 0, 0, 140), width=1)

    return ImageTk.PhotoImage(im)
