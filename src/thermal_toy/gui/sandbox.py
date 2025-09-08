# src/thermal_toy/gui/sandbox.py
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

import pandas as pd

from ..runtime import GameSession
from .sprite_factory import sprite_hvac, sprite_pv, sprite_battery, sprite_house_with_temp
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
        self.minsize(980, 760)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- options ----
        self.csv_path     = str(csv_path)
        self.game_days    = int(max(1, game_days))
        self.preview_days = int(max(1, min(2, preview_days)))
        self.lookahead_days = self.preview_days - 1          # 0 or 1
        self.speed_ms     = int(max(1, speed_ms))

        # consistent quadrant sizes (no scrolling)
        self.COL_W = 470       # quadrant width
        self.HOUSE_SIZE = (self.COL_W, 280)
        self.CHART_W = self.COL_W
        self.CH_H_TEMP = 180
        self.CH_H_PRICE = 150
        self.CH_H_WEATHER = 180

        # ---- engine/session ----
        # note: pass a session in to reuse one; otherwise create here
        self.session = session or GameSession(day_csv_path=self.csv_path)

        # ---- load series ----
        self.df_day = self._load_day(self.csv_path)
        self.dt     = float(self.df_day["dt_h"].iloc[0])
        self.dt_h   = self.dt

        self.hours    = self.df_day["hour_of_day"].to_numpy()
        self.days_col = self.df_day["day"].to_numpy()
        self.x_abs_h  = (self.hours + 24.0 * (self.days_col - 1)).astype(float)

        self.price = self.df_day["price_eur_per_kwh"].to_numpy()
        self.tout  = self.df_day["t_out_c"].to_numpy()
        self.pv    = self.df_day["solar_gen_kw_per_kwp"].to_numpy()

        self.steps_per_day   = int(round(24.0 / self.dt))
        self.total_steps_csv = int(len(self.df_day))
        self.T               = min(self.total_steps_csv, int(self.steps_per_day * self.game_days))

        # state
        self._tin_hist: list[float] = []
        self._k: int = 0
        self._last_info: dict = {}
        self.playing = False

        self._build()
        self._reset()

    # ---------- UI ----------
    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # 2×2 grid (no scrolling)
        grid = ttk.Frame(root)
        grid.pack(side="top", fill="both", expand=True)

        for c in (0, 1):
            grid.columnconfigure(c, weight=1, uniform="cols")
        for r in (0, 1):
            grid.rowconfigure(r, weight=1, uniform="rows")

        # Q1 (row0,col0): House with overlay
        q1 = ttk.Frame(grid)
        q1.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        self.house_label = ttk.Label(q1)
        self.house_label.pack(fill="both", expand=True)

        # Q2 (row0,col1): Charts notebook (3 tabs)
        q2 = ttk.Frame(grid)
        q2.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 8))
        self.nb = ttk.Notebook(q2)
        self.nb.pack(fill="both", expand=True)

        tab_temp = ttk.Frame(self.nb);  self.nb.add(tab_temp, text="Temp")
        tab_price = ttk.Frame(self.nb); self.nb.add(tab_price, text="Price")
        tab_weather = ttk.Frame(self.nb); self.nb.add(tab_weather, text="Weather + PV")

        self.chartA_label = ttk.Label(tab_temp);    self.chartA_label.pack(fill="x", pady=6)
        self.chartB_label = ttk.Label(tab_price);   self.chartB_label.pack(fill="x", pady=6)
        self.chartC_label = ttk.Label(tab_weather); self.chartC_label.pack(fill="x", pady=6)

        # Q3 (row1,col0): Device badges
        q3 = ttk.Frame(grid)
        q3.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        badges = ttk.Frame(q3); badges.pack(pady=6)
        self.hvac_label = ttk.Label(badges);  self.hvac_label.grid(row=0, column=0, padx=8, pady=6)
        self.pv_label   = ttk.Label(badges);  self.pv_label.grid(row=0, column=1, padx=8, pady=6)
        self.batt_label = ttk.Label(badges);  self.batt_label.grid(row=0, column=2, padx=8, pady=6)

        # Q4 (row1,col1): Controls
        q4 = ttk.Frame(grid)
        q4.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))

        controls = ttk.Frame(q4); controls.pack(anchor="n", pady=6)
        self.action_var = tk.DoubleVar(value=0.0)   # HVAC [-1, 1]
        self.pv_on_var  = tk.BooleanVar(value=False)
        self.soc_var    = tk.DoubleVar(value=0.5)   # Battery [0, 1]

        r = 0
        ttk.Label(controls, text="HVAC u").grid(row=r, column=0, sticky="w")
        ttk.Scale(controls, from_=-1.0, to=1.0, variable=self.action_var, length=320,
                  orient="horizontal", command=lambda *_: self._refresh_badges()
        ).grid(row=r, column=1, columnspan=2, sticky="ew"); r += 1

        ttk.Checkbutton(controls, text="PV ON", variable=self.pv_on_var,
                        command=self._refresh_badges).grid(row=r, column=1, sticky="w"); r += 1

        ttk.Label(controls, text="Battery SOC").grid(row=r, column=0, sticky="w")
        ttk.Scale(controls, from_=0.0, to=1.0, variable=self.soc_var, length=320,
                  orient="horizontal", command=lambda *_: self._refresh_badges()
        ).grid(row=r, column=1, columnspan=2, sticky="ew"); r += 1

        ttk.Button(controls, text="Step",  command=self._step,  width=12).grid(row=r, column=0, padx=4, pady=(6, 0))
        self.play_btn = ttk.Button(controls, text="▶ Play", command=self._toggle_play, width=12)
        self.play_btn.grid(row=r, column=1, padx=4, pady=(6, 0))
        ttk.Button(controls, text="Reset", command=self._reset, width=12).grid(row=r, column=2, padx=4, pady=(6, 0))

        # status line under grid (single line; still no scroll)
        self.status = ttk.Label(root, text="Ready.", anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

        # shortcuts
        self.bind("<space>",  lambda e: self._toggle_play())
        self.bind("<Return>", lambda e: self._step())
        self.bind("<Escape>", lambda e: self._on_close())

    # ---------- Session control ----------
    def _reset(self):
        info = self.session.reset()
        self._last_info = dict(info)
        self._tin_hist.clear()
        self._k = 0
        self.playing = False
        self.play_btn.config(text="▶ Play")
        self._refresh_all()
        self.status.config(text="Reset.")

    def _step(self):
        if self._k >= self.T:
            return
        u = float(self.action_var.get())
        info = self.session.step({"u": u})
        self._last_info = dict(info)
        self._k += 1
        self._tin_hist.append(info.get("Tin_c", float("nan")))
        self._refresh_all()
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
        self.after(self.speed_ms, self._loop)

    # ---------- Refresh helpers ----------
    def _refresh_all(self):
        self._refresh_house()
        self._refresh_badges()
        self._refresh_charts()

    def _refresh_house(self):
        cursor_h = self._k * self.dt
        hour_mod = cursor_h % 24.0
        bg_name  = time_of_day_sprite(hour_mod)

        day_idx = int(self.days_col[min(self._k, self.T - 1)])
        tin  = (self._tin_hist[-1] if self._tin_hist else float(self._last_info.get("Tin_c", 21.0)))
        tout = float(self.tout[min(self._k, self.T - 1)])

        step_cost     = float(self._last_info.get("cost_eur_step", 0.0))
        step_penalty  = float(self._last_info.get("comfort_penalty_eur_step", 0.0))
        step_reward   = float(self._last_info.get("reward", 0.0))
        cum_cost      = float(self._last_info.get("cum_energy_cost_eur", 0.0))
        cum_penalty   = float(self._last_info.get("cum_comfort_penalty_eur", 0.0))
        cum_reward    = float(self._last_info.get("cum_reward", 0.0))

        lines = [
            f"Day {day_idx}   t {self._k}/{self.T}   hour {hour_mod:04.2f}",
            f"Step  €: energy {step_cost:.3f}   comfort {step_penalty:.3f}   reward {step_reward:.3f}",
            f"Total €: energy {cum_cost:.2f}    comfort {cum_penalty:.2f}    reward {cum_reward:.2f}",
        ]
        house_img = sprite_house_with_temp(bg_name, tin_c=tin, tout_c=tout, size=self.HOUSE_SIZE, lines=tuple(lines))
        self.house_label.configure(image=house_img)
        self.house_label.image = house_img

    def _refresh_badges(self):
        self.hvac_img  = sprite_hvac(float(self.action_var.get()), size=(220, 220))
        self.pv_img    = sprite_pv(bool(self.pv_on_var.get()), size=(220, 220))
        self.batt_img  = sprite_battery(float(self.soc_var.get()), size=(220, 220))
        self.hvac_label.configure(image=self.hvac_img); self.hvac_label.image = self.hvac_img
        self.pv_label.configure(image=self.pv_img);     self.pv_label.image   = self.pv_img
        self.batt_label.configure(image=self.batt_img); self.batt_label.image = self.batt_img

    def _refresh_charts(self):
        # sliding window: today (and optionally tomorrow)
        cursor_h   = self._k * self.dt
        day_start  = math.floor(cursor_h / 24.0) * 24.0
        span_h     = (1 + self.lookahead_days) * 24.0
        win_start  = day_start
        win_end    = day_start + span_h

        k0 = max(0, int(round(win_start / self.dt)))
        k1 = min(self.T, int(round(win_end   / self.dt)))

        hours_rel = (self.x_abs_h[k0:k1] - win_start).tolist()
        price_win = self.price[k0:k1].tolist()
        tout_win  = self.tout[k0:k1].tolist()
        pv_win    = self.pv[k0:k1].tolist()

        # Tin history within the window
        past_len = max(0, min(self._k - k0, len(hours_rel)))
        tin_hist_win = self._tin_hist[-past_len:] if past_len > 0 else []

        temp_img = make_temp_chart_sprite(
            hours=hours_rel, tin_hist=tin_hist_win,
            comfort_L=21.0 - 1.0, comfort_U=21.0 + 1.0,
            size=(self.CHART_W, self.CH_H_TEMP),
            cursor_hour=(cursor_h - win_start),
        )
        self.chartA_label.configure(image=temp_img); self.chartA_label.image = temp_img

        price_img = make_price_chart_sprite(
            hours=hours_rel, price=price_win,
            size=(self.CHART_W, self.CH_H_PRICE),
            cursor_hour=(cursor_h - win_start),
        )
        self.chartB_label.configure(image=price_img); self.chartB_label.image = price_img

        weather_img = make_weather_pv_chart_sprite(
            hours=hours_rel, tout=tout_win, pv=pv_win,
            size=(self.CHART_W, self.CH_H_WEATHER),
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
                df["hour_of_day"] = (df["t"] * float(df["dt_h"].iloc[0])) % 24.0
            if "solar_gen_kw_per_kwp" not in df.columns:
                df["solar_gen_kw_per_kwp"] = 0.0
            if "day" not in df.columns:
                df["day"] = (df["t"] * df["dt_h"] // 24).astype(int) + 1
            return df
        except Exception:
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
