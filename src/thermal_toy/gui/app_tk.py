from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ..runtime.session import GameSession
from .theming import apply_theme
from .options import GuiOptions, edit_options

class WelcomeApp:
    def __init__(self, root: tk.Tk | None = None):
        self.root = root or tk.Tk()
        self.root.title("Smart Household — Toy RL Game")
        self.root.minsize(720, 420)

        self.options = GuiOptions()   # <-- hold gameplay + hvac + debug
        apply_theme(self.root)
        self._build()

        # Shortcuts
        self.root.bind("<Return>", lambda e: self._start_sandbox())
        self.root.bind("<Escape>", lambda e: self.root.quit())
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())

        # Windows DPI
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)  # type: ignore
        except Exception:
            pass

    # ---------- UI ----------
    def _build(self):
        outer = ttk.Frame(self.root, padding=24); outer.pack(fill="both", expand=True)

        hdr = ttk.Frame(outer); hdr.pack(fill="x", pady=(0, 16))
        ttk.Label(hdr, text="Smart Household", style="Title.TLabel", anchor="w").pack(anchor="w")
        ttk.Label(hdr, text="Tiny sandbox to juggle comfort vs. power.", style="Subtitle.TLabel", anchor="w").pack(anchor="w")

        body = ttk.Frame(outer); body.pack(fill="both", expand=True)
        btns = ttk.Frame(body); btns.pack(pady=12)

        self.btn_play = ttk.Button(btns, text="▶  Open Sandbox", command=self._start_sandbox, width=24)
        self.btn_demo = ttk.Button(btns, text="🤖 Quick RL Demo (stub)", command=self._start_rl_demo, width=24)
        self.btn_opts = ttk.Button(btns, text="⚙  Options", command=self._open_options, width=24)
        self.btn_quit = ttk.Button(btns, text="✖  Quit", command=self.root.quit, width=24)

        for i, b in enumerate([self.btn_play, self.btn_demo, self.btn_opts, self.btn_quit]):
            b.grid(row=i, column=0, pady=6, sticky="ew")

        blurb = ttk.Label(
            body,
            text=(
                "Welcome! This is just the front door.\n"
                "• Sandbox: manual control one step at a time.\n"
                "• RL Demo: placeholder that will run a pre-trained policy.\n"
                "• Options: choose devices, budgets & gameplay length.\n\n"
                "Press Enter to open the Sandbox, Esc to quit."
            ),
            style="Body.TLabel",
            justify="left",
        )
        blurb.pack(pady=12)

        self.status = ttk.Label(outer, text="Ready.", style="Status.TLabel", anchor="w")
        self.status.pack(fill="x", pady=(16, 0))

    # ---------- Actions ----------
    def _start_sandbox(self):
        from .sandbox import SandboxWindow
        opts = self.options
        SandboxWindow(self.root, **opts.as_sandbox_kwargs())
        dbg = " (debug ON)" if opts.debug else ""
        self.status.config(
            text=f"Sandbox: {opts.game_days}d, preview={opts.preview_days}d, speed={opts.speed_ms}ms{dbg}"
        )

    def _start_rl_demo(self):
        self.status.config(text="Running RL demo… (stub)")
        messagebox.showinfo(
            "RL Demo",
            "This would load a pre-trained policy and roll multiple days.\n"
            "Stub for now.",
        )

    def _open_options(self):
        def _applied(opts: GuiOptions):
            eur = opts.budget_eur()
            self.status.config(text=f"Options applied — budget≈{eur:,.0f} €".replace(",", " "))
        edit_options(self.root, self.options, on_apply=_applied)

    def _toggle_fullscreen(self):
        fs = self.root.attributes("-fullscreen")
        self.root.attributes("-fullscreen", not fs)

    # ---------- Loop ----------
    def run(self):
        self.root.mainloop()

def main():
    app = WelcomeApp()
    app.run()

if __name__ == "__main__":
    main()
