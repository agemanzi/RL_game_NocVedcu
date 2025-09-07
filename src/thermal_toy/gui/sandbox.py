from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

import pandas as pd

from ..runtime import GameSession
from .assets import load_sprite
from .sprite_factory import sprite_hvac, sprite_pv, sprite_battery
from .chart_sprites import (
    make_temp_chart_sprite,
    make_price_chart_sprite,
    make_weather_pv_chart_sprite,
)
from .sprite_factory import sprite_house_with_temp

def time_of_day_sprite(hour: float) -> str:
    if 6 <= hour < 11:  return "house_morning"
    if 11 <= hour < 16: return "house_midday"
    if 16 <= hour < 21: return "house_afternoon"
    return "house_night"

class SandboxWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc | None = None,
        session: GameSession | None = None,
        *,
        csv_path: str = "data/week01_prices_weather.csv",
        game_days: int = 7,
        preview_days: int = 2,     # 1 = today, 2 = today+tomorrow
        speed_ms: int = 120,
        **_,
    ):
        super().__init__(master)
        self.title("Sandbox — Manual Control")
        self.minsize(900, 860)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- options ----
        self.csv_path     = str(csv_path)
        self.game_days    = int(max(1, game_days))
        self.preview_days = int(max(1, min(2, preview_days)))
        self.lookahead_days = self.preview_days - 1          # 0 or 1
        self.speed_ms     = int(max(1, speed_ms))

        # ---- engine/session ----
        self.session = session or GameSession(day_csv_path=self.csv_path, debug=True)

        # ---- load series ----
        self.df_day = self._load_day(self.csv_path)
        self.dt     = float(self.df_day["dt_h"].iloc[0])     # alias for charts
        self.dt_h   = self.dt

        self.hours  = self.df_day["hour_of_day"].to_numpy()
        self.days_col = self.df_day["day"].to_numpy()
        # absolute hour across the whole horizon (0..)
        self.x_abs_h = (self.hours + 24.0 * (self.days_col - 1)).astype(float)

        self.price = self.df_day["price_eur_per_kwh"].to_numpy()
        self.tout  = self.df_day["t_out_c"].to_numpy()
        self.pv    = self.df_day["solar_gen_kw_per_kwp"].to_numpy()

        # steps per day + total steps available from CSV
        self.steps_per_day = int(round(24.0 / self.dt))
        self.total_steps_csv = int(len(self.df_day))
        # gameplay horizon = min(csv, requested days)
        self.T = min(self.total_steps_csv, int(self.steps_per_day * self.game_days))

        # state
        self._tin_hist: list[float] = []
        self._k: int = 0
        self.playing = False

        self._build()
        self._reset()

    # ---------- UI ----------
    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Paned: left visuals (house + badges) | right charts
        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes, padding=(0, 0, 10, 0))
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        # Left: background + device badges
        self.house_label = ttk.Label(left); self.house_label.pack(side="top", fill="x", pady=(0, 10))
        badges = ttk.Frame(left); badges.pack(side="top", fill="x")
        self.hvac_label = ttk.Label(badges);  self.hvac_label.grid(row=0, column=0, padx=8, pady=6)
        self.pv_label   = ttk.Label(badges);  self.pv_label.grid(row=0, column=1, padx=8, pady=6)
        self.batt_label = ttk.Label(badges);  self.batt_label.grid(row=0, column=2, padx=8, pady=6)

        # Right: stacked chart sprites
        self.chartA_label = ttk.Label(right); self.chartA_label.pack(side="top", fill="x", pady=(2, 6))
        self.chartB_label = ttk.Label(right); self.chartB_label.pack(side="top", fill="x", pady=(2, 6))
        self.chartC_label = ttk.Label(right); self.chartC_label.pack(side="top", fill="x", pady=(2, 6))

        # Bottom controls + readout
        bottom = ttk.Frame(root); bottom.pack(side="bottom", fill="x", pady=(10, 0))
        self.readout = ttk.Label(bottom, text="–", justify="left"); self.readout.pack(side="left", padx=(0, 16))

        controls = ttk.Frame(bottom); controls.pack(side="right")
        self.action_var = tk.DoubleVar(value=0.0)   # HVAC [-1, 1]
        self.pv_on_var  = tk.BooleanVar(value=False)
        self.soc_var    = tk.DoubleVar(value=0.5)   # Battery [0, 1]

        r = 0
        ttk.Label(controls, text="HVAC u").grid(row=r, column=0, sticky="w")
        ttk.Scale(controls, from_=-1.0, to=1.0, variable=self.action_var, length=320,
                  orient="horizontal", command=lambda *_: self._refresh_sprites()
        ).grid(row=r, column=1, columnspan=2, sticky="ew"); r += 1

        ttk.Checkbutton(controls, text="PV ON", variable=self.pv_on_var,
                        command=self._refresh_sprites).grid(row=r, column=1, sticky="w"); r += 1

        ttk.Label(controls, text="Battery SOC").grid(row=r, column=0, sticky="w")
        ttk.Scale(controls, from_=0.0, to=1.0, variable=self.soc_var, length=320,
                  orient="horizontal", command=lambda *_: self._refresh_sprites()
        ).grid(row=r, column=1, columnspan=2, sticky="ew"); r += 1

        ttk.Button(controls, text="Step",  command=self._step,  width=12).grid(row=r, column=0, padx=4, pady=(6, 0))
        self.play_btn = ttk.Button(controls, text="▶ Play", command=self._toggle_play, width=12)
        self.play_btn.grid(row=r, column=1, padx=4, pady=(6, 0))
        ttk.Button(controls, text="Reset", command=self._reset, width=12).grid(row=r, column=2, padx=4, pady=(6, 0))

        self.status = ttk.Label(root, text="Ready.", anchor="w"); self.status.pack(fill="x", pady=(6, 0))

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
        self._tin_hist.append(info.get("Tin_c", float("nan")))
        self._refresh_charts()
        self._set_readout(info)
        self._refresh_sprites()
        self.status.config(text=f"Step {self._k}")
        if self._k >= self.T:
            self.playing = False
            self.play_btn.config(text="▶ Play")
            messagebox.showinfo("Run complete", "Reached the end of the scenario.")

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
        self.after(self.speed_ms, self._loop)  # ~8 FPS

    # ---------- Helpers ----------
    def _set_readout(self, info: dict):
        cursor_h = self._k * self.dt
        day_idx = int(self.days_col[min(self._k, self.T - 1)])
        hour_mod = cursor_h % 24.0
        hvac = float(self.action_var.get())
        pv   = bool(self.pv_on_var.get())
        soc  = float(self.soc_var.get())
        L, U = 21.0 - 1.0, 21.0 + 1.0  # (optional: pull from config/rw params)
        self.readout.config(
            text=(
                f"day = {day_idx} | t = {self._k}/{self.T} | hour = {hour_mod:4.2f}\n"
                f"Tin = {info.get('Tin_c', 0.0):.2f} °C (comfort {L:.1f}–{U:.1f} °C)\n"
                f"HVAC u = {hvac:+.2f}  |  PV = {'ON' if pv else 'OFF'}  |  SOC = {int(round(soc*100))}%"
            )
        )

    def _refresh_sprites(self):
        cursor_h = self._k * self.dt
        hour_mod = cursor_h % 24.0
        bg_name = time_of_day_sprite(hour_mod)
        tin = self._tin_hist[-1] if self._tin_hist else float(self.df_day["t_out_c"].iloc[0])
        tout = self.df_day["t_out_c"].iloc[self._k]
        self.house_img = sprite_house_with_temp(bg_name, tin_c=tin, tout_c=tout, size=(460, 260))
        self.house_label.configure(image=self.house_img); self.house_label.image = self.house_img

        self.hvac_img  = sprite_hvac(float(self.action_var.get()), size=(220, 220))
        self.pv_img    = sprite_pv(bool(self.pv_on_var.get()), size=(220, 220))
        self.batt_img  = sprite_battery(float(self.soc_var.get()), size=(220, 220))
        self.hvac_label.configure(image=self.hvac_img); self.hvac_label.image = self.hvac_img
        self.pv_label.configure(image=self.pv_img);     self.pv_label.image   = self.pv_img
        self.batt_label.configure(image=self.batt_img); self.batt_label.image = self.batt_img

    def _refresh_charts(self):
        # Window: current day start .. + (1 + lookahead_days) days (in absolute hours)
        cursor_h = self._k * self.dt
        day_start_h = math.floor(cursor_h / 24.0) * 24.0
        span_h = (1 + self.lookahead_days) * 24.0
        win_start = day_start_h
        win_end = day_start_h + span_h

        # Convert to step indices (aligned with dt)
        k0 = int(round(win_start / self.dt))
        k1 = int(round(min(self.T, win_end / self.dt)))

        hours_rel = (self.x_abs_h[k0:k1] - win_start).tolist()
        price_win = self.price[k0:k1].tolist()
        tout_win  = self.tout[k0:k1].tolist()
        pv_win    = self.pv[k0:k1].tolist()

        # Tin history in the same window (up to current step)
        past_len = min(self._k - k0, len(hours_rel))
        past_len = max(0, past_len)
        tin_hist_win = self._tin_hist[-past_len:] if past_len > 0 else []
        hours_past_rel = hours_rel[:past_len]

        # A) Temp vs comfort band
        temp_img = make_temp_chart_sprite(
            hours=hours_rel,
            tin_hist=tin_hist_win if tin_hist_win else [],
            comfort_L=21.0 - 1.0,
            comfort_U=21.0 + 1.0,
            size=(480, 180),
            cursor_hour=(cursor_h - win_start),
        )
        self.chartA_label.configure(image=temp_img); self.chartA_label.image = temp_img

        # B) Price
        price_img = make_price_chart_sprite(
            hours=hours_rel, price=price_win, size=(480, 140),
            cursor_hour=(cursor_h - win_start),
        )
        self.chartB_label.configure(image=price_img); self.chartB_label.image = price_img

        # C) Weather + PV
        weather_img = make_weather_pv_chart_sprite(
            hours=hours_rel, tout=tout_win, pv=pv_win, size=(480, 180),
            cursor_hour=(cursor_h - win_start),
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
            need = ["t", "dt_h", "t_out_c", "price_eur_per_kwh"]
            for c in need:
                if c not in df.columns:
                    raise ValueError(f"CSV missing column: {c}")
            if "hour_of_day" not in df.columns:
                df["hour_of_day"] = df["t"] * float(df["dt_h"].iloc[0]) % 24.0
            if "solar_gen_kw_per_kwp" not in df.columns:
                df["solar_gen_kw_per_kwp"] = 0.0
            if "day" not in df.columns:
                df["day"] = (df["t"] * df["dt_h"] // 24).astype(int) + 1
            return df
        except Exception:
            # minimal fallback (1 day)
            return pd.DataFrame(
                {
                    "t": [0, 1, 2, 3],
                    "dt_h": [0.25] * 4,
                    "hour_of_day": [0.0, 0.25, 0.5, 0.75],
                    "t_out_c": [0.0, 0.0, 0.0, 0.0],
                    "price_eur_per_kwh": [0.0, 0.0, 0.0, 0.0],
                    "solar_gen_kw_per_kwp": [0.0, 0.0, 0.0, 0.0],
                    "day": [1, 1, 1, 1],
                }
            )
