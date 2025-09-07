from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from tkinter import ttk

# Matplotlib embed for Tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


@dataclass(frozen=True)
class ComfortSpec:
    t_set_c: float = 21.0
    width_c: float = 2.0

    @property
    def L(self) -> float: return self.t_set_c - 0.5 * self.width_c
    @property
    def U(self) -> float: return self.t_set_c + 0.5 * self.width_c


class ChartsPanel(ttk.Frame):
    """
    3 stacked charts, shared 0–24h x-axis (or from CSV 'hour_of_day'):
      A) Tin vs comfort band
      B) Price
      C) Tout + PV (dual y-axes)
    """
    def __init__(self, master, df: pd.DataFrame, *, comfort: ComfortSpec = ComfortSpec()):
        super().__init__(master)
        self.df = df.reset_index(drop=True).copy()
        self.comfort = comfort

        # --- derive x-axis (hours) ---
        if "hour_of_day" in self.df.columns:
            self.hours = self.df["hour_of_day"].to_numpy(dtype=float)
        else:
            dt_h = float(self.df["dt_h"].iloc[0])
            self.hours = np.arange(self.df.shape[0], dtype=float) * dt_h

        # --- series ---
        self.price = self.df["price_eur_per_kwh"].to_numpy(dtype=float)
        self.tout  = self.df["t_out_c"].to_numpy(dtype=float)
        self.pv    = self.df.get("solar_gen_kw_per_kwp", pd.Series(np.zeros_like(self.hours))).to_numpy(dtype=float)

        # placeholder for Tin history (grow as we step)
        self.tin_hist: list[float] = []

        # --- figure layout ---
        self.fig = Figure(figsize=(7.5, 5.2), dpi=100)
        gs = self.fig.add_gridspec(nrows=3, ncols=1, height_ratios=[1.2, 1.0, 1.2], hspace=0.25)

        # A) Tin vs comfort band
        self.axA = self.fig.add_subplot(gs[0])
        self.axA.set_ylabel("°C")
        self.axA.set_xlim(self.hours[0], self.hours[-1])
        self.axA.set_title("Indoor temperature vs comfort")
        # comfort band fill
        self.axA.axhspan(comfort.L, comfort.U, color="tab:green", alpha=0.12, label="Comfort band")
        self.axA.axhline(comfort.L, color="tab:green", lw=1, alpha=0.6)
        self.axA.axhline(comfort.U, color="tab:green", lw=1, alpha=0.6)
        # Tin line (empty initially)
        self.line_tin, = self.axA.plot(self.hours, np.full_like(self.hours, np.nan), lw=2.0, label="Tin")
        self.axA.legend(loc="upper right", frameon=False)

        # B) Price
        self.axB = self.fig.add_subplot(gs[1], sharex=self.axA)
        self.axB.set_ylabel("€/kWh")
        self.axB.set_title("Market price")
        self.line_price, = self.axB.plot(self.hours, self.price, lw=2.0)

        # C) Weather (Tout) + PV (twin y)
        self.axC = self.fig.add_subplot(gs[2], sharex=self.axA)
        self.axC_twin = self.axC.twinx()
        self.axC.set_ylabel("Tout (°C)")
        self.axC_twin.set_ylabel("PV (per kWp)")
        self.axC.set_title("Weather & Solar forecast")
        self.line_tout, = self.axC.plot(self.hours, self.tout, lw=2.0, label="Tout")
        # area for PV
        self.area_pv = self.axC_twin.fill_between(self.hours, self.pv, step=None, alpha=0.25)
        # tidy
        self.axC.set_xlabel("Hour of day")

        # vertical cursor on all axes
        self.vA = self.axA.axvline(self.hours[0], color="k", lw=1, alpha=0.6)
        self.vB = self.axB.axvline(self.hours[0], color="k", lw=1, alpha=0.6)
        self.vC = self.axC.axvline(self.hours[0], color="k", lw=1, alpha=0.6)

        # --- canvas ---
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # API used by Sandbox
    def reset(self):
        self.tin_hist.clear()
        self._update_tin_line()
        self._move_cursor(0)
        self.canvas.draw_idle()

    def append_tin(self, value_c: float):
        self.tin_hist.append(float(value_c))
        self._update_tin_line()

    def set_cursor_index(self, k: int):
        k = int(max(0, min(k, len(self.hours) - 1)))
        self._move_cursor(k)

    # --- internals ---
    def _update_tin_line(self):
        n = len(self.tin_hist)
        y = np.full_like(self.hours, np.nan, dtype=float)
        if n > 0:
            y[:n] = np.asarray(self.tin_hist, dtype=float)
        self.line_tin.set_ydata(y)

    def _move_cursor(self, k: int):
        x = self.hours[k]
        for v in (self.vA, self.vB, self.vC):
            v.set_xdata([x, x])
