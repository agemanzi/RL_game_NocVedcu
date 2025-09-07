# src/thermal_toy/gui/theming.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    # Use available theme closest to modern look
    for candidate in ("clam", "alt", "default", "vista", "xpnative"):
        try:
            style.theme_use(candidate)
            break
        except Exception:
            continue

    # Base fonts
    style.configure(".", font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 22))
    style.configure("Subtitle.TLabel", foreground="#666", font=("Segoe UI", 12))
    style.configure("Body.TLabel", foreground="#222")
    style.configure("Status.TLabel", foreground="#555")

    # Buttons
    style.configure("TButton", padding=(10, 6))
    style.map("TButton", relief=[("pressed", "sunken"), ("!pressed", "flat")])

    # Frame padding
    style.configure("TFrame", background=style.lookup("TFrame", "background"))
