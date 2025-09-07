# src/thermal_toy/gui/sandbox.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from ..runtime import DummySession
from .assets import load_sprite                # static backgrounds from assets/images
from .sprite_factory import sprite_hvac, sprite_pv, sprite_battery  # dynamic device sprites


def time_of_day_sprite(hour: float) -> str:
    """Pick a house scene name from hour-of-day."""
    if 6 <= hour < 11:  return "house_morning"
    if 11 <= hour < 16: return "house_midday"
    if 16 <= hour < 21: return "house_afternoon"
    return "house_night"


class SandboxWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc | None = None, session: Optional[DummySession] = None, *, dt_h: float = 0.25):
        super().__init__(master)
        self.title("Sandbox — Manual Control")
        self.minsize(900, 620)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.session = session or DummySession()
        self.dt_h = float(dt_h)
        self.T = int(24 / self.dt_h)  # one-day loop
        self.playing = False
        self._after_id: Optional[str] = None

        self._build()
        self._reset()

    # ---------- UI ----------
    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # --- Row 1: big house background ---
        self.house_label = ttk.Label(root)
        self.house_label.pack(fill="x", pady=(0, 10))

        ttk.Separator(root, orient="horizontal").pack(fill="x", pady=8)

        # --- Row 2: device badges (HVAC, PV, Battery) ---
        badges = ttk.Frame(root)
        badges.pack(fill="x")
        self.hvac_label = ttk.Label(badges);  self.hvac_label.grid(row=0, column=0, padx=8, pady=6)
        self.pv_label   = ttk.Label(badges);  self.pv_label.grid(row=0, column=1, padx=8, pady=6)
        self.batt_label = ttk.Label(badges);  self.batt_label.grid(row=0, column=2, padx=8, pady=6)

        ttk.Separator(root, orient="horizontal").pack(fill="x", pady=8)

        # --- Row 3: readout + controls ---
        grid = ttk.Frame(root); grid.pack(fill="x")
        self.readout = ttk.Label(grid, text="–", style="Body.TLabel", justify="left")
        self.readout.grid(row=0, column=0, sticky="w", padx=(0, 16))

        controls = ttk.Frame(grid); controls.grid(row=0, column=1, sticky="e")

        # controls state
        self.action_var = tk.DoubleVar(value=0.0)   # HVAC [-1, 1]
        self.pv_on_var  = tk.BooleanVar(value=False)
        self.soc_var    = tk.DoubleVar(value=0.5)   # Battery [0, 1]

        r = 0
        ttk.Label(controls, text="HVAC u").grid(row=r, column=0, sticky="w")
        ttk.Scale(controls, from_=-1.0, to=1.0, variable=self.action_var, length=320,
                  orient="horizontal", command=lambda *_: self._refresh_sprites()
        ).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        ttk.Checkbutton(controls, text="PV ON", variable=self.pv_on_var,
                        command=self._refresh_sprites).grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Label(controls, text="Battery SOC").grid(row=r, column=0, sticky="w")
        ttk.Scale(controls, from_=0.0, to=1.0, variable=self.soc_var, length=320,
                  orient="horizontal", command=lambda *_: self._refresh_sprites()
        ).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1

        # step/play/reset
        ttk.Button(controls, text="Step",  command=self._step,       width=12).grid(row=r, column=0, padx=4, pady=(6,0))
        self.play_btn = ttk.Button(controls, text="▶ Play", command=self._toggle_play, width=12)
        self.play_btn.grid(row=r, column=1, padx=4, pady=(6,0))
        ttk.Button(controls, text="Reset", command=self._reset,      width=12).grid(row=r, column=2, padx=4, pady=(6,0))

        # footer
        self.status = ttk.Label(root, text="Ready.", style="Status.TLabel", anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

        # shortcuts
        self.bind("<space>",  lambda e: self._toggle_play())
        self.bind("<Return>", lambda e: self._step())
        self.bind("<Escape>", lambda e: self._on_close())

    # ---------- Session control ----------
    def _reset(self):
        info = self.session.reset()
        self.k = 0
        self.done = False
        self._set_readout(info)
        self._refresh_sprites()
        self.status.config(text="Reset.")

    def _step(self):
        if self.done:
            return
        # Map GUI → (dummy) env action; for now we only pass HVAC u.
        # PV on/off and SOC are visual—wire them to env later.
        act = float(self.action_var.get())
        info = self.session.step({"u": act})
        self.k += 1
        self._set_readout(info)
        self._refresh_sprites()
        self.status.config(text=f"Step {self.k}")
        if self.k >= self.T:
            self.done = True
            self.playing = False
            self.play_btn.config(text="▶ Play")
            messagebox.showinfo("Day complete", "The day has ended. Reset to play again.")
            self.status.config(text="Day complete.")

    def _toggle_play(self):
        if self.done:
            return
        self.playing = not self.playing
        self.play_btn.config(text="❚❚ Pause" if self.playing else "▶ Play")
        if self.playing:
            self._loop()

    def _loop(self):
        if not self.playing or self.done:
            return
        self._step()
        self.after(120, self._loop)  # ~8 FPS

    # ---------- Helpers ----------
    def _set_readout(self, info: dict):
        hour = (self.k * self.dt_h) % 24.0
        hvac = float(self.action_var.get())
        pv   = bool(self.pv_on_var.get())
        soc  = float(self.soc_var.get())
        self.readout.config(
            text=(
                f"t = {self.k}/{self.T}  |  hour = {hour:4.2f}\n"
                f"Tin = {info.get('Tin_c', 0.0):.2f} °C\n"
                f"HVAC u = {hvac:+.2f}   |   PV = {'ON' if pv else 'OFF'}   |   SOC = {int(round(soc*100))}%"
            )
        )

    def _refresh_sprites(self):
        # background by time-of-day (uses assets/images/house_*.png)
        hour = (self.k * self.dt_h) % 24.0
        self.house_img = load_sprite(time_of_day_sprite(hour), size=(860, 260))
        self.house_label.configure(image=self.house_img); self.house_label.image = self.house_img

        # dynamic device sprites (code-generated)
        self.hvac_img  = sprite_hvac(float(self.action_var.get()), size=(220, 220))
        self.pv_img    = sprite_pv(bool(self.pv_on_var.get()), size=(220, 220))
        self.batt_img  = sprite_battery(float(self.soc_var.get()), size=(220, 220))

        self.hvac_label.configure(image=self.hvac_img);   self.hvac_label.image = self.hvac_img
        self.pv_label.configure(image=self.pv_img);       self.pv_label.image   = self.pv_img
        self.batt_label.configure(image=self.batt_img);   self.batt_label.image = self.batt_img

    def _on_close(self):
        self.playing = False
        self.destroy()
