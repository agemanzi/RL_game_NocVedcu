from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, List

from pathlib import Path
import pandas as pd
import numpy as np

from ..runtime import DummySession
from .assets import load_sprite
from .sprite_factory import sprite_hvac, sprite_pv, sprite_battery
from .chart_sprites import (
    make_temp_chart_sprite,
    make_price_chart_sprite,
    make_weather_pv_chart_sprite,
)

def time_of_day_sprite(hour: float) -> str:
    if 6 <= hour < 11:  return "house_morning"
    if 11 <= hour < 16: return "house_midday"
    if 16 <= hour < 21: return "house_afternoon"
    return "house_night"


class SandboxWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc | None = None,
        session: Optional[DummySession] = None,
        *,
        dt_h: float = 0.25,
        csv_path: str = "data/day01_prices_weather.csv",
        game_days: int = 1,          # NEW: total playable days (1..7)
        preview_days: int = 1,       # NEW: chart window length (1=today, 2=today+tomorrow)
        speed_ms: int = 120,         # NEW: play speed (ms per step)
    ):
        super().__init__(master)
        self.title("Sandbox — Manual Control")
        self.minsize(980, 860)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Session/engine
        self.session = session or DummySession()

        # Gameplay config
        self.dt_h = float(dt_h)
        self.csv_path = csv_path
        self.game_days = int(max(1, min(7, game_days)))
        self.preview_days = int(max(1, min(2, preview_days)))
        self.speed_ms = int(max(30, speed_ms))

        # Load timeseries (day or week)
        self.df = self._load_day(self.csv_path)
        self.dt_h_csv = float(self.df["dt_h"].iloc[0])
        if not np.isclose(self.dt_h_csv, self.dt_h):
            # keep running, but align to CSV dt (engine uses config)
            self.dt_h = self.dt_h_csv

        # Derived sizes
        self.steps_per_day = int(round(24.0 / self.dt_h))
        self.T_total = int(self.df.shape[0])
        self.T = int(min(self.T_total, self.game_days * self.steps_per_day))

        # Series (numpy)
        self.hours_all = self.df["hour_of_day"].to_numpy(dtype=float)
        self.price_all = self.df["price_eur_per_kwh"].to_numpy(dtype=float)
        self.tout_all  = self.df["t_out_c"].to_numpy(dtype=float)
        self.pv_all    = self.df["solar_gen_kw_per_kwp"].to_numpy(dtype=float)

        # Runtime trackers
        self._tin_hist: List[float] = []   # per-step Tin (for charting)
        self._k: int = 0
        self.playing: bool = False
        self._comfort_L: float = 20.0
        self._comfort_U: float = 22.0

        # UI state (controls)
        self.action_var = tk.DoubleVar(value=0.0)   # HVAC [-1, 1]
        self.pv_on_var  = tk.BooleanVar(value=False)
        self.soc_var    = tk.DoubleVar(value=0.5)   # Battery [0, 1]

        self._build()
        self._reset()

    # ---------- UI ----------
    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Split: left visuals, right charts
        self.panes = ttk.Panedwindow(root, orient="horizontal")
        self.panes.pack(side="top", fill="both", expand=True)

        left = ttk.Frame(self.panes, padding=(0, 0, 8, 0))
        right = ttk.Frame(self.panes)
        self.panes.add(left, weight=1)
        self.panes.add(right, weight=1)

        # Left: house + device badges
        self.house_label = ttk.Label(left)
        self.house_label.pack(side="top", fill="x", pady=(0, 10))

        badges = ttk.Frame(left); badges.pack(side="top", fill="x")
        self.hvac_label = ttk.Label(badges);  self.hvac_label.grid(row=0, column=0, padx=8, pady=6)
        self.pv_label   = ttk.Label(badges);  self.pv_label.grid(row=0, column=1, padx=8, pady=6)
        self.batt_label = ttk.Label(badges);  self.batt_label.grid(row=0, column=2, padx=8, pady=6)

        # Right: stacked chart images
        self.chartA_label = ttk.Label(right)  # Temp vs comfort
        self.chartA_label.pack(side="top", fill="x", pady=(2, 6))
        self.chartB_label = ttk.Label(right)  # Price
        self.chartB_label.pack(side="top", fill="x", pady=(2, 6))
        self.chartC_label = ttk.Label(right)  # Weather + PV
        self.chartC_label.pack(side="top", fill="x", pady=(2, 6))

        # Bottom bar: readout + controls
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x", pady=(10, 0))

        self.readout = ttk.Label(bottom, text="–", justify="left")
        self.readout.pack(side="left", padx=(0, 16))

        controls = ttk.Frame(bottom); controls.pack(side="right")

        r = 0
        ttk.Label(controls, text="HVAC u").grid(row=r, column=0, sticky="w")
        ttk.Scale(
            controls, from_=-1.0, to=1.0, variable=self.action_var, length=320,
            orient="horizontal", command=lambda *_: self._refresh_sprites()
        ).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        ttk.Checkbutton(
            controls, text="PV ON", variable=self.pv_on_var,
            command=self._refresh_sprites
        ).grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Label(controls, text="Battery SOC").grid(row=r, column=0, sticky="w")
        ttk.Scale(
            controls, from_=0.0, to=1.0, variable=self.soc_var, length=320,
            orient="horizontal", command=lambda *_: self._refresh_sprites()
        ).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        ttk.Button(controls, text="Step",  command=self._step,  width=12).grid(row=r, column=0, padx=4, pady=(6, 0))
        self.play_btn = ttk.Button(controls, text="▶ Play", command=self._toggle_play, width=12)
        self.play_btn.grid(row=r, column=1, padx=4, pady=(6, 0))
        ttk.Button(controls, text="Reset", command=self._reset, width=12).grid(row=r, column=2, padx=4, pady=(6, 0))

        # Footer status
        self.status = ttk.Label(root, text="Ready.", anchor="w")
        self.status.pack(side="bottom", fill="x", pady=(8, 0))

        # Shortcuts
        self.bind("<space>",  lambda e: self._toggle_play())
        self.bind("<Return>", lambda e: self._step())
        self.bind("<Escape>", lambda e: self._on_close())

    # ---------- Session control ----------
    def _reset(self):
        info = self.session.reset()
        self._tin_hist.clear()
        self._k = 0
        self.playing = False
        self.play_btn.config(text="▶ Play")

        # comfort band if provided by engine
        self._comfort_L = float(info.get("comfort_L_c", self._comfort_L))
        self._comfort_U = float(info.get("comfort_U_c", self._comfort_U))

        # initial draw
        self._set_readout(info)
        self._refresh_sprites()
        self._refresh_charts()
        self.status.config(text="Reset.")

    def _step(self):
        if self._k >= self.T:
            return

        act = float(self.action_var.get())
        info = self.session.step({"u": act})
        self._k += 1

        # track Tin for charts
        self._tin_hist.append(float(info.get("Tin_c", float("nan"))))

        # update comfort if present
        self._comfort_L = float(info.get("comfort_L_c", self._comfort_L))
        self._comfort_U = float(info.get("comfort_U_c", self._comfort_U))

        # refresh
        self._set_readout(info)
        self._refresh_sprites()
        self._refresh_charts()

        # end of simulation?
        if self._k >= self.T:
            self.playing = False
            self.play_btn.config(text="▶ Play")
            days_played = min(self.game_days, int(np.ceil(self.T / self.steps_per_day)))
            messagebox.showinfo("Simulation complete", f"The {days_played}-day run has ended. Reset to play again.")
            self.status.config(text="Run complete.")
        else:
            self.status.config(text=f"Step {self._k}")

    def _toggle_play(self):
        if self._k >= self.T:
            return
        self.playing = not self.playing
        self.play_btn.config(text="❚❚ Pause" if self.playing else "▶ Play")
        if self.playing:
            self._loop()

    def _loop(self):
        if not self.playing or self._k >= self.T:
            return
        self._step()
        # use configured speed
        self.after(self.speed_ms, self._loop)

    # ---------- Helpers ----------
    def _set_readout(self, info: dict):
        # day and hour
        day_idx = self._k // self.steps_per_day
        hour = (self._k % self.steps_per_day) * self.dt_h
        hvac = float(self.action_var.get())
        pv   = bool(self.pv_on_var.get())
        soc  = float(self.soc_var.get())
        self.readout.config(
            text=(
                f"day = {day_idx+1}/{self.game_days} | t = {self._k}/{self.T} | hour = {hour:4.2f}\n"
                f"Tin = {info.get('Tin_c', 0.0):.2f} °C (comfort {self._comfort_L:.1f}–{self._comfort_U:.1f} °C)\n"
                f"HVAC u = {hvac:+.2f}   |   PV = {'ON' if pv else 'OFF'}   |   SOC = {int(round(soc*100))}%"
            )
        )

    def _refresh_sprites(self):
        # background by local hour of current day
        hour = (self._k % self.steps_per_day) * self.dt_h
        self.house_img = load_sprite(time_of_day_sprite(hour), size=(460, 260))
        self.house_label.configure(image=self.house_img); self.house_label.image = self.house_img

        # dynamic device sprites
        self.hvac_img  = sprite_hvac(float(self.action_var.get()), size=(220, 220))
        self.pv_img    = sprite_pv(bool(self.pv_on_var.get()), size=(220, 220))
        self.batt_img  = sprite_battery(float(self.soc_var.get()), size=(220, 220))

        self.hvac_label.configure(image=self.hvac_img);   self.hvac_label.image = self.hvac_img
        self.pv_label.configure(image=self.pv_img);       self.pv_label.image   = self.pv_img
        self.batt_label.configure(image=self.batt_img);   self.batt_label.image = self.batt_img

    def _refresh_charts(self):
        """
        Show a sliding window: [today .. today+preview_days), clipped by available data.
        """
        # window indices
        day_idx = self._k // self.steps_per_day
        start = day_idx * self.steps_per_day
        end = min(self.T_total, start + self.preview_days * self.steps_per_day)

        # slice series
        hours = list(self.hours_all[start:end])
        price = list(self.price_all[start:end])
        tout  = list(self.tout_all[start:end])
        pv    = list(self.pv_all[start:end])

        # Tin history for window (only the part we’ve already simulated)
        tin_hist = []
        if self._tin_hist:
            # history length may be < start; slice safely
            hstart = min(start, len(self._tin_hist))
            hend   = min(self._k, len(self._tin_hist))
            tin_hist = list(self._tin_hist[hstart:hend])

        # cursor hour (local within current day)
        cursor_h = (self._k % self.steps_per_day) * self.dt_h

        # A) Temp vs comfort band
        temp_img = make_temp_chart_sprite(
            hours, tin_hist, comfort_L=self._comfort_L, comfort_U=self._comfort_U,
            size=(460, 180), cursor_hour=cursor_h
        )
        self.chartA_label.configure(image=temp_img); self.chartA_label.image = temp_img

        # B) Price
        price_img = make_price_chart_sprite(
            hours, price, size=(460, 140), cursor_hour=cursor_h
        )
        self.chartB_label.configure(image=price_img); self.chartB_label.image = price_img

        # C) Weather + PV
        weather_img = make_weather_pv_chart_sprite(
            hours, tout, pv, size=(460, 180), cursor_hour=cursor_h
        )
        self.chartC_label.configure(image=weather_img); self.chartC_label.image = weather_img

    def _on_close(self):
        self.playing = False
        self.destroy()

    # ---------- Data ----------
    @staticmethod
    def _load_day(path: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(path)
            needed = ["t", "dt_h", "t_out_c", "price_eur_per_kwh"]
            for c in needed:
                if c not in df.columns:
                    raise ValueError(f"CSV missing column: {c}")
            if "hour_of_day" not in df.columns:
                # derive repeating 0..24h cycles
                dt = float(df["dt_h"].iloc[0])
                df["hour_of_day"] = (df["t"].to_numpy(dtype=float) * dt) % 24.0
            if "solar_gen_kw_per_kwp" not in df.columns:
                df["solar_gen_kw_per_kwp"] = 0.0
            return df
        except Exception:
            # minimal fallback
            return pd.DataFrame(
                {
                    "t": [0, 1, 2, 3],
                    "dt_h": [0.25] * 4,
                    "hour_of_day": [0.0, 0.25, 0.5, 0.75],
                    "t_out_c": [0.0, 0.0, 0.0, 0.0],
                    "price_eur_per_kwh": [0.0, 0.0, 0.0, 0.0],
                    "solar_gen_kw_per_kwp": [0.0, 0.0, 0.0, 0.0],
                }
            )
