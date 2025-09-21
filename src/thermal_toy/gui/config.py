# src/thermal_toy/gui/config.py
# Central config for chart “splines” (PIL-drawn sprites) and styling.

from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Sequence

RGBA = Tuple[int, int, int, int]
Rect = Tuple[int, int, int, int]  # (L, T, R, B)
Size = Tuple[int, int]            # (W, H)


# ---------------------------
# Fonts
# ---------------------------
# Tried in order; first available is used.
FONT_CANDIDATES: Sequence[str] = ("Segoe UI", "Arial", "DejaVuSans")

FONT_SIZE_TICK: int   = 11
FONT_SIZE_LABEL: int  = 12
FONT_SIZE_DEFAULT: int = 12


# ---------------------------
# Colors
# ---------------------------
# Backgrounds
COLOR_BG: RGBA            = (255, 255, 255, 255)

# Frame/axes/ticks/text
COLOR_FRAME: RGBA         = (180, 180, 180, 255)
COLOR_TICK: RGBA          = (150, 150, 150, 255)
COLOR_TEXT: RGBA          = (80, 80, 80, 255)
COLOR_TITLE: RGBA         = (70, 70, 70, 255)

# Cursor line
COLOR_CURSOR: RGBA        = (0, 0, 0, 160)

# Series (lines/areas)
COLOR_TIN_LINE: RGBA      = (30, 30, 30, 255)
COLOR_PRICE_LINE: RGBA    = (60, 120, 220, 255)
COLOR_TOUT_LINE: RGBA     = (40, 40, 40, 255)
COLOR_PV_AREA: RGBA       = (255, 200, 100, 90)

# Comfort band
COLOR_COMFORT_FILL: RGBA  = (120, 200, 120, 40)
COLOR_COMFORT_EDGE: RGBA  = (80, 160, 80, 180)


# ---------------------------
# Line widths
# ---------------------------
WIDTH_FRAME: int          = 1
WIDTH_TICK: int           = 1
WIDTH_SERIES: int         = 2
WIDTH_CURSOR: int         = 1
WIDTH_COMFORT_EDGE: int   = 1


# ---------------------------
# Chart sizes & layout
# ---------------------------
# Default chart sprite sizes (match current behavior)
SIZE_TEMP: Size    = (860, 180)
SIZE_PRICE: Size   = (860, 140)
SIZE_WEATHER: Size = (860, 180)

# Plot rectangles (inside each image): (L, T, R, B)
# These replicate the numbers currently in chart_sprites.py
PLOTRECT_TEMP: Rect    = (50, 22, SIZE_TEMP[0] - 12,  SIZE_TEMP[1] - 30)
PLOTRECT_PRICE: Rect   = (50, 18, SIZE_PRICE[0] - 12, SIZE_PRICE[1] - 28)
# leave room on the right for PV y-axis labels
PLOTRECT_WEATHER: Rect = (50, 22, SIZE_WEATHER[0] - 50, SIZE_WEATHER[1] - 30)


# ---------------------------
# Auto-range / padding
# ---------------------------
# Extra padding around data-derived y-limits
PAD_RATIO_TEMP: float    = 0.15
PAD_RATIO_PRICE: float   = 0.12
PAD_RATIO_WEATHER: float = 0.12

# Weather/PV fallbacks
WEATHER_TOUT_FALLBACK: Tuple[float, float] = (-5.0, 30.0)
PV_MINMAX: Tuple[float, float]             = (0.0, 0.1)  # min->0.0, max at least 0.1


# ---------------------------
# Ticks
# ---------------------------
# X ticks: use 0..24 step 4 for day-long windows
X_TICK_START: float = 0.0
X_TICK_END: float   = 24.0
X_TICK_STEP: float  = 4.0

# Y ticks
TEMP_Y_STEP: float  = 2.0
PRICE_Y_MIN_STEP: float = 0.05  # minimum step; actual step rounds to nearest 0.05

# When zoomed (shorter window), number of divisions to aim for
XTICKS_TARGET_DIVS: int = 6


# ---------------------------
# Labels
# ---------------------------
LABEL_TEMP_LEFT: str     = "Tin (°C)"
LABEL_PRICE_LEFT: str    = "Price (€/kWh)"
LABEL_WEATHER_LEFT: str  = "Tout (°C)"
LABEL_PV_RIGHT: str      = "PV (per kWp)"


# ---------------------------
# Utility containers to simplify swapping configs per chart
# ---------------------------
@dataclass(frozen=True)
class ChartConfig:
    size: Size
    plot_rect: Rect
    pad_ratio: float

TEMP_CONFIG   = ChartConfig(size=SIZE_TEMP,    plot_rect=PLOTRECT_TEMP,    pad_ratio=PAD_RATIO_TEMP)
PRICE_CONFIG  = ChartConfig(size=SIZE_PRICE,   plot_rect=PLOTRECT_PRICE,   pad_ratio=PAD_RATIO_PRICE)
WEATHER_CONFIG= ChartConfig(size=SIZE_WEATHER, plot_rect=PLOTRECT_WEATHER, pad_ratio=PAD_RATIO_WEATHER)


# ---------------------------
# Helpers (optional)
# ---------------------------
def price_tick_step(y_span: float) -> float:
    """
    Choose a nice price tick step, rounded to the nearest 0.05,
    but never less than PRICE_Y_MIN_STEP.
    """
    if y_span <= 0:
        return PRICE_Y_MIN_STEP
    raw = max(PRICE_Y_MIN_STEP, y_span / 5.0)
    # round to nearest 0.05
    step = round(raw / 0.05) * 0.05
    return max(step, PRICE_Y_MIN_STEP)


def x_ticks_for_window(xmin: float, xmax: float):
    """
    Default: 0..24 step 4 for full-day.
    If the window is shorter than half a day, return ~6 divisions.
    """
    rng = max(0.0, xmax - xmin)
    if rng >= 12.0:
        start, end, step = X_TICK_START, X_TICK_END, X_TICK_STEP
        xs = []
        v = start
        while v <= end + 1e-9:
            xs.append(round(v, 6))
            v += step
        return xs
    # short window -> ~6 ticks
    step = max(1.0, rng / XTICKS_TARGET_DIVS) if rng > 0 else 1.0
    # align to integers where possible
    base = math.ceil(xmin / step) * step if step > 0 else xmin
    xs = []
    v = base
    while v <= xmax + 1e-9:
        xs.append(round(v, 6))
        v += step
    return xs
