from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Tuple

import pandas as pd

from ..runtime import GameSession
from .sprite_factory import sprite_hvac, sprite_pv, sprite_battery, sprite_house_from_png

from .chart_sprites import (
    make_temp_chart_sprite,
    make_price_chart_sprite,
    make_weather_pv_chart_sprite,
)

from .output_splines import (
    make_energy_breakdown_sprite,
    make_actions_sprite,
    make_rewards_sprite,
)
HVAC_MAX_KW = 5.0      # fallback scale for hvac power if runtime doesn’t provide it
BATTERY_MAX_KW = 3.0   # fallback scale for battery power
PV_KWP = 1.0           # if your pv series is “per kWp”, multiply by plant size here

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
        self.session = session or GameSession(day_csv_path=self.csv_path)

        # ---- load series ----
        self.df_day = self._load_day(self.csv_path)
        self.dt     = float(self.df_day["dt_h"].iloc[0])
        self.dt_h   = self.dt

        # weather/price axes
        self.hours    = self.df_day["hour_of_day"].to_numpy()
        self.days_col = self.df_day["day"].to_numpy()
        self.x_abs_h  = (self.hours + 24.0 * (self.days_col - 1)).astype(float)

        self.price = self.df_day["price_eur_per_kwh"].to_numpy()
        self.tout  = self.df_day["t_out_c"].to_numpy()
        self.pv    = self.df_day["solar_gen_kw_per_kwp"].to_numpy()

        self.steps_per_day   = int(round(24.0 / self.dt))
        self.total_steps_csv = int(len(self.df_day))
        self.T               = min(self.total_steps_csv, int(self.steps_per_day * self.game_days))

        # ---- people/base-load profile ----
        self.df_profile = self._load_profile("data/profile.csv")
        self.people_kw  = self._align_profile_to_main(self.df_profile, self.dt, self.total_steps_csv)

        # ---- state & histories ----
        self._tin_hist: list[float] = []
        self._u_hvac_hist: list[float] = []
        self._u_batt_hist: list[float] = []
        self._hvac_kw_hist: list[float] = []
        self._batt_kw_hist: list[float] = []
        self._opex_hist: list[float] = []
        self._penalty_hist: list[float] = []

        self._k: int = 0
        self._last_info: dict = {}
        self.playing = False

        self._build()
        self._reset()

    # ---------- UI ----------
    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Top-level 3-column grid
        grid = ttk.Frame(root)
        grid.pack(side="top", fill="both", expand=True)

        for c in (0, 1, 2):
            grid.columnconfigure(c, weight=1, uniform="cols")
        grid.rowconfigure(0, weight=1)

        # =========================
        # LEFT COLUMN: House → Devices → Controls
        # =========================
        left = tk.LabelFrame(grid, text="Simulation", relief="groove", borderwidth=2, padx=6, pady=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=3, uniform="leftcol")  # House
        left.rowconfigure(1, weight=0)                     # Sep
        left.rowconfigure(2, weight=2, uniform="leftcol")  # Devices
        left.rowconfigure(3, weight=0)                     # Sep
        left.rowconfigure(4, weight=2, uniform="leftcol")  # Controls

        # --- House ---
        q_house = ttk.Frame(left)
        q_house.grid(row=0, column=0, sticky="nsew")
        self.house_label = ttk.Label(q_house)
        self.house_label.pack(fill="both", expand=True, pady=(0, 6))

        ttk.Separator(left, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=6)

        # --- Devices (badges) ---
        q_devices = ttk.Frame(left)
        q_devices.grid(row=2, column=0, sticky="nsew")
        badges = ttk.Frame(q_devices)
        badges.pack(pady=6)
        self.hvac_label = ttk.Label(badges);  self.hvac_label.grid(row=0, column=0, padx=8, pady=6)
        self.pv_label   = ttk.Label(badges);  self.pv_label.grid(row=0, column=1, padx=8, pady=6)
        self.batt_label = ttk.Label(badges);  self.batt_label.grid(row=0, column=2, padx=8, pady=6)

        ttk.Separator(left, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=6)

        # --- Controls ---
        q_controls = ttk.Frame(left)
        q_controls.grid(row=4, column=0, sticky="nsew")

        controls = ttk.Frame(q_controls)
        controls.pack(anchor="n", pady=6, fill="x")

        # state vars
        self.action_var = tk.DoubleVar(value=0.0)   # HVAC [-1, 1]
        self.pv_on_var  = tk.BooleanVar(value=False)
        self.soc_var    = tk.DoubleVar(value=0.5)   # Battery [0, 1]

        r = 0
        ttk.Label(controls, text="HVAC u").grid(row=r, column=0, sticky="w")
        ttk.Scale(
            controls, from_=-1.0, to=1.0, variable=self.action_var, length=320,
            orient="horizontal", command=lambda *_: self._refresh_badges()
        ).grid(row=r, column=1, columnspan=2, sticky="ew"); r += 1

        ttk.Checkbutton(
            controls, text="PV ON", variable=self.pv_on_var,
            command=self._refresh_badges
        ).grid(row=r, column=1, sticky="w"); r += 1

        ttk.Label(controls, text="Battery SOC").grid(row=r, column=0, sticky="w")
        ttk.Scale(
            controls, from_=0.0, to=1.0, variable=self.soc_var, length=320,
            orient="horizontal", command=lambda *_: self._refresh_badges()
        ).grid(row=r, column=1, columnspan=2, sticky="ew"); r += 1

        ttk.Button(controls, text="Step", command=self._step, width=12)\
            .grid(row=r, column=0, padx=4, pady=(6, 0))

        # create play_btn before _reset() runs
        self.play_btn = ttk.Button(controls, text="▶ Play", command=self._toggle_play, width=12)
        self.play_btn.grid(row=r, column=1, padx=4, pady=(6, 0))

        ttk.Button(controls, text="Reset", command=self._reset, width=12)\
            .grid(row=r, column=2, padx=4, pady=(6, 0))

        controls.columnconfigure(1, weight=1)  # sliders stretch

        # =========================
        # MIDDLE COLUMN: Outputs (placeholders)
        # =========================
        mid = tk.LabelFrame(grid, text="Outputs", relief="groove", borderwidth=2, padx=6, pady=6)
        mid.grid(row=0, column=1, sticky="nsew", padx=8, pady=0)
        mid.columnconfigure(0, weight=1)
        for rr in (0, 1, 2):
            mid.rowconfigure(rr, weight=1, uniform="midrows")

        def _out_row(parent, rix: int, title: str, attr: str):
            row = tk.LabelFrame(parent, text=title, relief="ridge", borderwidth=1, padx=6, pady=6)
            row.grid(row=rix, column=0, sticky="nsew", pady=(0 if rix == 0 else 8, 0))
            placeholder = ttk.Label(row, text="(plot placeholder)", relief="sunken", anchor="center")
            placeholder.pack(fill="both", expand=True, ipady=12)
            setattr(self, attr, placeholder)

        _out_row(mid, 0, "HVAC heat", "out_hvac_label")
        _out_row(mid, 1, "PV generation", "out_pv_label")
        _out_row(mid, 2, "Battery charge / discharge", "out_batt_label")

        # =========================
        # RIGHT COLUMN: Charts (framed like Outputs)
        # =========================
        right = tk.LabelFrame(grid, text="Charts", relief="groove", borderwidth=2, padx=6, pady=6)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0), pady=0)

        charts = ttk.Frame(right)
        charts.pack(fill="both", expand=True)
        charts.columnconfigure(0, weight=1)
        for rr in (0, 1, 2):
            charts.rowconfigure(rr, weight=1, uniform="chartrows")

        def _chart_row(parent, rix: int, title: str, attr: str):
            row = tk.LabelFrame(parent, text=title, relief="ridge", borderwidth=1, padx=6, pady=6)
            row.grid(row=rix, column=0, sticky="nsew", pady=(0 if rix == 0 else 8, 0))
            lbl = ttk.Label(row, relief="flat", anchor="center")
            lbl.pack(fill="both", expand=True)
            setattr(self, attr, lbl)

        _chart_row(charts, 0, "Temp",         "chartA_label")
        _chart_row(charts, 1, "Price",        "chartB_label")
        _chart_row(charts, 2, "Weather + PV", "chartC_label")

        # Re-render charts when any label is resized
        for lbl in (self.chartA_label, self.chartB_label, self.chartC_label):
            lbl.bind("<Configure>", lambda e: self._refresh_charts())

        # Status line
        self.status = ttk.Label(root, text="Ready.", anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

        # Shortcuts
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

        # -------- collect histories for middle-column outputs --------
        self._u_hvac_hist.append(u)
        batt_u = float(info.get("u_batt", info.get("batt_u", 0.0)))
        self._u_batt_hist.append(batt_u)

        hvac_kw = float(info.get("hvac_kw", info.get("Q_hvac_kw", info.get("P_hvac_kw", u * HVAC_MAX_KW))))
        batt_kw = float(info.get("battery_kw", info.get("P_batt_kw", info.get("batt_kw", batt_u * BATTERY_MAX_KW))))
        self._hvac_kw_hist.append(hvac_kw)
        self._batt_kw_hist.append(batt_kw)

        self._opex_hist.append(float(info.get("cost_eur_step", 0.0)))
        self._penalty_hist.append(float(info.get("comfort_penalty_eur_step", 0.0)))
        # ----------------------------------------------------------------

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
        self._refresh_outputs()   # NEW
        
        
    def _refresh_outputs(self):
        # Use the same sliding window as the right-column charts
        cursor_h   = self._k * self.dt
        day_start  = math.floor(cursor_h / 24.0) * 24.0
        span_h     = (1 + self.lookahead_days) * 24.0
        win_start  = day_start
        win_end    = day_start + span_h

        k0 = max(0, int(round(win_start / self.dt)))
        k1 = min(self.T, int(round(win_end   / self.dt)))

        hours_rel = (self.x_abs_h[k0:k1] - win_start).tolist()

        # Slices from static series
        people_win = self.people_kw[k0:k1].tolist()
        pv_win_abs = (self.pv[k0:k1] * PV_KWP).tolist()

        # Histories (only up to current step)
        past_len = max(0, min(self._k - k0, len(hours_rel)))

        def tail(hist, n=len(hours_rel)):
            if past_len <= 0:
                return [0.0] * n
            xs = hist[-past_len:]
            if len(xs) < n:
                xs = xs + [0.0] * (n - len(xs))
            return xs[:n]

        hvac_kw_win = tail(self._hvac_kw_hist)
        batt_kw_win = tail(self._batt_kw_hist)
        u_hvac_win  = tail(self._u_hvac_hist)
        u_batt_win  = tail(self._u_batt_hist)
        opex_win    = tail(self._opex_hist)
        pen_win     = tail(self._penalty_hist)

        # Sizes that match the framed areas (use existing placeholder labels)
        sz_energy  = self._label_size(getattr(self, "out_hvac_label"), (self.CHART_W, self.CH_H_TEMP))
        sz_actions = self._label_size(getattr(self, "out_pv_label"),   (self.CHART_W, self.CH_H_TEMP))
        sz_rewards = self._label_size(getattr(self, "out_batt_label"), (self.CHART_W, self.CH_H_TEMP))

        # 1) Energy: net + stacked components (people + hvac ± batt − pv)
        img_energy = make_energy_breakdown_sprite(
            hours=hours_rel,
            people_kw=people_win,
            hvac_kw=hvac_kw_win,
            battery_kw=batt_kw_win,
            pv_kw=pv_win_abs,
            size=sz_energy,
            cursor_hour=(cursor_h - win_start),
            margins=(12, 10, 12, 16),
            outer_pad=(14, 14, 14, 14),
        )

        # 2) Actions: u_hvac & u_batt in [-1, +1]
        img_actions = make_actions_sprite(
            hours=hours_rel,
            u_hvac=u_hvac_win,
            u_batt=u_batt_win,
            size=sz_actions,
            cursor_hour=(cursor_h - win_start),
            margins=(12, 10, 12, 16),
            outer_pad=(14, 14, 14, 14),
        )

        # 3) Rewards: stacked OPEX + comfort penalty (both ≥0)
        img_rewards = make_rewards_sprite(
            hours=hours_rel,
            opex_eur_step=opex_win,
            comfort_penalty_eur_step=pen_win,
            size=sz_rewards,
            cursor_hour=(cursor_h - win_start),
            margins=(12, 10, 12, 16),
            outer_pad=(14, 14, 14, 14),
        )

        # Push to the placeholders you already have
        self.out_hvac_label.configure(image=img_energy);  self.out_hvac_label.image  = img_energy
        self.out_pv_label.configure(image=img_actions);   self.out_pv_label.image    = img_actions
        self.out_batt_label.configure(image=img_rewards); self.out_batt_label.image  = img_rewards


    def _refresh_house(self):
        cursor_h = self._k * self.dt
        hour_mod = cursor_h % 24.0

        time_minute = int(round(hour_mod * 60.0))

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

        house_img = sprite_house_from_png(
            time_minute=time_minute,
            tin_c=tin,
            tout_c=tout,
            size=self.HOUSE_SIZE,
            lines=tuple(lines),
            with_sky=True,
        )

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
        # Window for today (+ optional tomorrow)
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

        past_len = max(0, min(self._k - k0, len(hours_rel)))
        tin_hist_win = self._tin_hist[-past_len:] if past_len > 0 else []

        # Sizes that match the framed chart areas
        sz_temp   = self._label_size(self.chartA_label, (self.CHART_W, self.CH_H_TEMP))
        sz_price  = self._label_size(self.chartB_label, (self.CHART_W, self.CH_H_PRICE))
        sz_weath  = self._label_size(self.chartC_label, (self.CHART_W, self.CH_H_WEATHER))

        temp_img = make_temp_chart_sprite(
            hours=hours_rel, tin_hist=tin_hist_win,
            comfort_L=21.0 - 1.0, comfort_U=21.0 + 1.0,
            size=sz_temp,cursor_hour=cursor_h - win_start,
            margins=(12, 10, 12, 12), outer_pad=(20,20,20,20),  # extra for time badge
        )
        self.chartA_label.configure(image=temp_img); self.chartA_label.image = temp_img

        price_img = make_price_chart_sprite(
            hours=hours_rel, price=price_win,
            size=sz_price,cursor_hour=cursor_h - win_start,
            margins=(12, 10, 12, 12), outer_pad=(30,30,30,30),
        )
        self.chartB_label.configure(image=price_img); self.chartB_label.image = price_img

        weather_img = make_weather_pv_chart_sprite(
            hours=hours_rel, tout=tout_win, pv=pv_win,
            size=sz_weath,cursor_hour=cursor_h - win_start,
            margins=(12, 10, 36, 12), outer_pad=(10,10,10,10),  # extra right for PV ticks
        )
        self.chartC_label.configure(image=weather_img); self.chartC_label.image = weather_img

    def _on_close(self):
        self.playing = False
        self.destroy()

    def _label_size(self, lbl: tk.Widget, fallback: Tuple[int,int]) -> Tuple[int,int]:
        w, h = lbl.winfo_width(), lbl.winfo_height()
        if w < 10 or h < 10:
            return fallback
        return (w, h)
    
    def _align_profile_to_main(self, df_prof: pd.DataFrame, dt_main: float, N_main: int):
        """
        Align profile series to the main absolute-hour axis via linear interpolation.
        """
        import numpy as np

        # main axis in hours
        t_main = np.arange(N_main, dtype=float) * dt_main

        # source axis in hours
        dt_src = float(df_prof["dt_h"].iloc[0])
        t_src = df_prof["t"].to_numpy(dtype=float) * dt_src
        y_src = df_prof["people_kw"].to_numpy(dtype=float)

        if len(t_src) < 2:
            return np.zeros(N_main, dtype=float)

        y = np.interp(t_main, t_src, y_src, left=y_src[0], right=y_src[-1])
        return y


    # ---------- Data ----------
    @staticmethod
    def _load_profile(path: str) -> pd.DataFrame:
        """
        Expects columns: t, dt_h and one of:
        - 'people_kw' (preferred)
        - or fallback: 'consumption_kw', 'load_kw'
        Returns a DataFrame with ['t','dt_h','people_kw'].
        """
        try:
            df = pd.read_csv(path)
            if "t" not in df.columns or "dt_h" not in df.columns:
                raise ValueError("profile.csv must contain 't' and 'dt_h'.")

            for cand in ("people_kw", "consumption_kw", "load_kw"):
                if cand in df.columns:
                    if cand != "people_kw":
                        df = df.rename(columns={cand: "people_kw"})
                    break
            else:
                df["people_kw"] = 0.0

            return df[["t", "dt_h", "people_kw"]].copy()
        except Exception:
            # minimal fallback
            return pd.DataFrame({"t": [0, 1, 2, 3], "dt_h": [0.25] * 4, "people_kw": [0.0] * 4})


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
