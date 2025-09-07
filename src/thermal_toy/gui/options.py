from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass

@dataclass
class GuiOptions:
    # -------- Gameplay (NEW) --------
    csv_path: str = "data/week01_prices_weather.csv"   # can be a day file too
    game_days: int = 7                                  # 1..7
    preview_days: int = 2                               # 1 (today) or 2 (today+tomorrow)
    speed_ms: int = 120                                 # ms per step when playing

    # -------- HVAC sizing & efficiency (existing) --------
    hvac_heat_kw: float = 3.0
    hvac_cool_kw: float = 2.5
    cop_heat: float = 3.0
    cop_cool: float = 3.0

    # -------- Debug prints (existing) --------
    debug: bool = False

    # -------- Flat-rate capex model (existing) --------
    pv_kwp: float = 0.0
    batt_kwh: float = 0.0
    rate_hp_eur_per_kw: float = 700.0
    rate_pv_eur_per_kwp: float = 900.0
    rate_batt_eur_per_kwh: float = 300.0

    def budget_eur(self) -> float:
        return (
            self.hvac_heat_kw * self.rate_hp_eur_per_kw
            + self.pv_kwp * self.rate_pv_eur_per_kwp
            + self.batt_kwh * self.rate_batt_eur_per_kwh
        )

    def as_overrides(self) -> dict:
        # Keys understood by Engine
        return {
            "hp_q_heat_max_kw_th": float(self.hvac_heat_kw),
            "hp_q_cool_max_kw_th": float(self.hvac_cool_kw),
            "hp_cop_heat": float(self.cop_heat),
            "hp_cop_cool": float(self.cop_cool),
        }

    def as_sandbox_kwargs(self) -> dict:
        # Handed to SandboxWindow for multi-day & speed behavior
        return {
            "csv_path": self.csv_path,
            "game_days": int(self.game_days),
            "preview_days": int(self.preview_days),
            "speed_ms": int(self.speed_ms),
        }

class OptionsWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, opts: GuiOptions, on_apply):
        super().__init__(master)
        self.title("Options")
        self.resizable(False, False)
        self.opts = opts
        self.on_apply = on_apply

        pad = {"padx": 8, "pady": 6}
        frm = ttk.Frame(self, padding=12); frm.pack(fill="both", expand=True)

        # -------- Gameplay (NEW) --------
        ttk.Label(frm, text="Gameplay").grid(row=0, column=0, sticky="w", **pad)
        gp = ttk.Frame(frm); gp.grid(row=1, column=0, sticky="ew")
        gp.columnconfigure(1, weight=1)

        self.var_csv = tk.StringVar(value=self.opts.csv_path)
        ttk.Label(gp, text="CSV path:").grid(row=0, column=0, sticky="w")
        ttk.Entry(gp, textvariable=self.var_csv, width=42).grid(row=0, column=1, sticky="ew")

        self.var_days = tk.IntVar(value=self.opts.game_days)
        ttk.Label(gp, text="Game length (days):").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(gp, from_=1, to=7, textvariable=self.var_days, width=8).grid(row=1, column=1, sticky="w")

        self.var_prev = tk.IntVar(value=self.opts.preview_days)
        ttk.Label(gp, text="Chart preview (days):").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(gp, from_=1, to=2, textvariable=self.var_prev, width=8).grid(row=2, column=1, sticky="w")

        self.var_speed = tk.IntVar(value=self.opts.speed_ms)
        ttk.Label(gp, text="Play speed (ms/step):").grid(row=3, column=0, sticky="w")
        ttk.Spinbox(gp, from_=30, to=2000, increment=10, textvariable=self.var_speed, width=8).grid(row=3, column=1, sticky="w")

        ttk.Separator(frm, orient="horizontal").grid(row=2, column=0, sticky="ew", **pad)

        # -------- HVAC (existing) --------
        ttk.Label(frm, text="HVAC sizing & COP").grid(row=3, column=0, sticky="w", **pad)
        body = ttk.Frame(frm); body.grid(row=4, column=0, columnspan=2, sticky="ew")
        body.columnconfigure(1, weight=1)

        self.var_heat = tk.DoubleVar(value=self.opts.hvac_heat_kw)
        self.var_cool = tk.DoubleVar(value=self.opts.hvac_cool_kw)
        self.var_cop_h = tk.DoubleVar(value=self.opts.cop_heat)
        self.var_cop_c = tk.DoubleVar(value=self.opts.cop_cool)

        ttk.Label(body, text="Heat cap (kW_th):").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(body, from_=0.0, to=20.0, increment=0.1, textvariable=self.var_heat, width=8,
                    command=self._update_budget).grid(row=0, column=1, sticky="w")

        ttk.Label(body, text="Cool cap (kW_th):").grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Spinbox(body, from_=0.0, to=20.0, increment=0.1, textvariable=self.var_cool, width=8,
                    command=self._update_budget).grid(row=0, column=3, sticky="w")

        ttk.Label(body, text="COP heat:").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(body, from_=1.0, to=8.0, increment=0.1, textvariable=self.var_cop_h, width=8
                    ).grid(row=1, column=1, sticky="w")
        ttk.Label(body, text="COP cool:").grid(row=1, column=2, sticky="w", padx=(16, 0))
        ttk.Spinbox(body, from_=1.0, to=8.0, increment=0.1, textvariable=self.var_cop_c, width=8
                    ).grid(row=1, column=3, sticky="w")

        ttk.Separator(frm, orient="horizontal").grid(row=5, column=0, sticky="ew", **pad)

        # -------- Budget (existing) --------
        ttk.Label(frm, text="Budget estimate (flat rates)").grid(row=6, column=0, sticky="w", **pad)
        cap = ttk.Frame(frm); cap.grid(row=7, column=0, sticky="ew")
        cap.columnconfigure(1, weight=1)

        self.var_pv = tk.DoubleVar(value=self.opts.pv_kwp)
        self.var_batt = tk.DoubleVar(value=self.opts.batt_kwh)
        self.var_rate_hp = tk.DoubleVar(value=self.opts.rate_hp_eur_per_kw)
        self.var_rate_pv = tk.DoubleVar(value=self.opts.rate_pv_eur_per_kwp)
        self.var_rate_batt = tk.DoubleVar(value=self.opts.rate_batt_eur_per_kwh)

        ttk.Label(cap, text="PV (kWp):").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(cap, from_=0.0, to=50.0, increment=0.5, textvariable=self.var_pv, width=8,
                    command=self._update_budget).grid(row=0, column=1, sticky="w")
        ttk.Label(cap, text="Battery (kWh):").grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Spinbox(cap, from_=0.0, to=200.0, increment=1.0, textvariable=self.var_batt, width=8,
                    command=self._update_budget).grid(row=0, column=3, sticky="w")

        ttk.Label(cap, text="Rate HP (€/kW_th):").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(cap, from_=0.0, to=5000.0, increment=50.0, textvariable=self.var_rate_hp, width=8,
                    command=self._update_budget).grid(row=1, column=1, sticky="w")

        ttk.Label(cap, text="Rate PV (€/kWp):").grid(row=1, column=2, sticky="w", padx=(16, 0))
        ttk.Spinbox(cap, from_=0.0, to=5000.0, increment=50.0, textvariable=self.var_rate_pv, width=8,
                    command=self._update_budget).grid(row=1, column=3, sticky="w")

        ttk.Label(cap, text="Rate Batt (€/kWh):").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(cap, from_=0.0, to=5000.0, increment=50.0, textvariable=self.var_rate_batt, width=8,
                    command=self._update_budget).grid(row=2, column=1, sticky="w")

        self.lbl_budget = ttk.Label(frm, text="Budget: – €")
        self.lbl_budget.grid(row=8, column=0, sticky="w", **pad)

        ttk.Separator(frm, orient="horizontal").grid(row=9, column=0, sticky="ew", **pad)

        # -------- Debug (existing) --------
        dbg = ttk.Frame(frm); dbg.grid(row=10, column=0, sticky="w", **pad)
        self.var_debug = tk.BooleanVar(value=self.opts.debug)
        ttk.Checkbutton(dbg, text="Enable debug prints", variable=self.var_debug).pack(side="left")

        # -------- Buttons --------
        btns = ttk.Frame(frm); btns.grid(row=11, column=0, sticky="e", **pad)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="OK", command=self._apply).pack(side="right")

        self._update_budget()

    def _update_budget(self):
        tmp = GuiOptions(
            # gameplay not needed for the budget number
            hvac_heat_kw=float(self.var_heat.get()),
            hvac_cool_kw=float(self.var_cool.get()),
            cop_heat=float(self.var_cop_h.get()),
            cop_cool=float(self.var_cop_c.get()),
            debug=bool(self.var_debug.get()),
            pv_kwp=float(self.var_pv.get()),
            batt_kwh=float(self.var_batt.get()),
            rate_hp_eur_per_kw=float(self.var_rate_hp.get()),
            rate_pv_eur_per_kwp=float(self.var_rate_pv.get()),
            rate_batt_eur_per_kwh=float(self.var_rate_batt.get()),
        )
        eur = tmp.budget_eur()
        self.lbl_budget.config(text=f"Budget: {eur:,.0f} €".replace(",", " "))

    def _apply(self):
        # Gameplay
        self.opts.csv_path = str(self.var_csv.get())
        self.opts.game_days = int(self.var_days.get())
        self.opts.preview_days = int(self.var_prev.get())
        self.opts.speed_ms = int(self.var_speed.get())

        # HVAC
        self.opts.hvac_heat_kw = float(self.var_heat.get())
        self.opts.hvac_cool_kw = float(self.var_cool.get())
        self.opts.cop_heat = float(self.var_cop_h.get())
        self.opts.cop_cool = float(self.var_cop_c.get())

        # Debug + budget params
        self.opts.debug = bool(self.var_debug.get())
        self.opts.pv_kwp = float(self.var_pv.get())
        self.opts.batt_kwh = float(self.var_batt.get())
        self.opts.rate_hp_eur_per_kw = float(self.var_rate_hp.get())
        self.opts.rate_pv_eur_per_kwp = float(self.var_rate_pv.get())
        self.opts.rate_batt_eur_per_kwh = float(self.var_rate_batt.get())

        if callable(self.on_apply):
            self.on_apply(self.opts)
        self.destroy()

def edit_options(master: tk.Misc, options: GuiOptions, on_apply):
    OptionsWindow(master, options, on_apply)

__all__ = ["GuiOptions", "OptionsWindow", "edit_options"]
