from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from pathlib import Path
import pandas as pd

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
    ):
        super().__init__(master)
        self.title("Sandbox — Manual Control")
        self.minsize(900, 860)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.session = session or DummySession()
        self.dt_h = float(dt_h)
        self.csv_path = csv_path
        self.playing = False

        # data
        self.df_day = self._load_day(self.csv_path)
        self.hours = self.df_day.get("hour_of_day", self.df_day["t"] * float(self.df_day["dt_h"].iloc[0])).to_numpy()
        self.price = self.df_day["price_eur_per_kwh"].to_numpy()
        self.tout  = self.df_day["t_out_c"].to_numpy()
        self.pv    = self.df_day.get("solar_gen_kw_per_kwp", pd.Series(0, index=self.df_day.index)).to_numpy()

        self.T = int(self.df_day.shape[0])
        self._tin_hist: list[float] = []
        self._k: int = 0

        self._build()
        self._reset()

    # ---------- UI ----------
    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # ---------- BOTTOM controls pinned ----------
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x")

        # Readout (left)
        self.readout = ttk.Label(bottom, text="–", justify="left")
        self.readout.pack(side="left", padx=(0, 16))

        # Controls (right)
        controls = ttk.Frame(bottom)
        controls.pack(side="right")

        self.action_var = tk.DoubleVar(value=0.0)   # HVAC [-1, 1]
        self.pv_on_var  = tk.BooleanVar(value=False)
        self.soc_var    = tk.DoubleVar(value=0.5)   # Battery [0, 1]

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
        footer = ttk.Frame(root)
        footer.pack(side="bottom", fill="x")
        self.status = ttk.Label(footer, text="Ready.", anchor="w")
        self.status.pack(fill="x", pady=(6, 0))

        # ---------- TOP visuals ----------
        self.house_label = ttk.Label(root)
        self.house_label.pack(side="top", fill="x", pady=(0, 10))

        ttk.Separator(root, orient="horizontal").pack(side="top", fill="x", pady=8)

        badges = ttk.Frame(root)
        badges.pack(side="top", fill="x")
        self.hvac_label = ttk.Label(badges);  self.hvac_label.grid(row=0, column=0, padx=8, pady=6)
        self.pv_label   = ttk.Label(badges);  self.pv_label.grid(row=0, column=1, padx=8, pady=6)
        self.batt_label = ttk.Label(badges);  self.batt_label.grid(row=0, column=2, padx=8, pady=6)

        ttk.Separator(root, orient="horizontal").pack(side="top", fill="x", pady=8)

        # ---------- Chart sprites (stacked) ----------
        charts = ttk.Frame(root)
        charts.pack(side="top", fill="both", expand=True)

        self.chartA_label = ttk.Label(charts)  # Temp vs comfort
        self.chartA_label.pack(side="top", fill="x", pady=(2, 4))

        self.chartB_label = ttk.Label(charts)  # Price
        self.chartB_label.pack(side="top", fill="x", pady=(2, 4))

        self.chartC_label = ttk.Label(charts)  # Weather + PV
        self.chartC_label.pack(side="top", fill="x", pady=(2, 4))

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

        # charts initial draw
        self._refresh_charts()
        self._set_readout(info)
        self._refresh_sprites()
        self.status.config(text="Reset.")

    def _step(self):
        if self._k >= self.T:
            return
        act = float(self.action_var.get())
        info = self.session.step({"u": act})
        self._k += 1

        # Update Tin history + charts
        self._tin_hist.append(info.get("Tin_c", float("nan")))
        self._refresh_charts()

        self._set_readout(info)
        self._refresh_sprites()
        self.status.config(text=f"Step {self._k}")
        if self._k >= self.T:
            self.playing = False
            self.play_btn.config(text="▶ Play")
            messagebox.showinfo("Day complete", "The day has ended. Reset to play again.")
            self.status.config(text="Day complete.")

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
        self.after(120, self._loop)  # ~8 FPS

    # ---------- Helpers ----------
    def _set_readout(self, info: dict):
        hour = (self._k * float(self.df_day["dt_h"].iloc[0])) % 24.0
        hvac = float(self.action_var.get())
        pv   = bool(self.pv_on_var.get())
        soc  = float(self.soc_var.get())
        self.readout.config(
            text=(
                f"t = {self._k}/{self.T}  |  hour = {hour:4.2f}\n"
                f"Tin = {info.get('Tin_c', 0.0):.2f} °C\n"
                f"HVAC u = {hvac:+.2f}   |   PV = {'ON' if pv else 'OFF'}   |   SOC = {int(round(soc*100))}%"
            )
        )

    def _refresh_sprites(self):
        # background
        hour = (self._k * float(self.df_day["dt_h"].iloc[0])) % 24.0
        self.house_img = load_sprite(time_of_day_sprite(hour), size=(860, 260))
        self.house_label.configure(image=self.house_img); self.house_label.image = self.house_img

        # device badges
        self.hvac_img  = sprite_hvac(float(self.action_var.get()), size=(220, 220))
        self.pv_img    = sprite_pv(bool(self.pv_on_var.get()), size=(220, 220))
        self.batt_img  = sprite_battery(float(self.soc_var.get()), size=(220, 220))

        self.hvac_label.configure(image=self.hvac_img);   self.hvac_label.image = self.hvac_img
        self.pv_label.configure(image=self.pv_img);       self.pv_label.image   = self.pv_img
        self.batt_label.configure(image=self.batt_img);   self.batt_label.image = self.batt_img

    def _refresh_charts(self):
        # Current cursor hour
        cursor_h = float(self.hours[min(self._k, len(self.hours)-1)])

        # A) Temp vs comfort band
        temp_img = make_temp_chart_sprite(
            self.hours, self._tin_hist, comfort_L=21.0-1.0, comfort_U=21.0+1.0,
            size=(860, 180), cursor_hour=cursor_h
        )
        self.chartA_label.configure(image=temp_img); self.chartA_label.image = temp_img

        # B) Price
        price_img = make_price_chart_sprite(
            self.hours, self.price, size=(860, 140), cursor_hour=cursor_h
        )
        self.chartB_label.configure(image=price_img); self.chartB_label.image = price_img

        # C) Weather + PV
        weather_img = make_weather_pv_chart_sprite(
            self.hours, self.tout, self.pv, size=(860, 180), cursor_hour=cursor_h
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
                df["hour_of_day"] = df["t"] * float(df["dt_h"].iloc[0])
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
