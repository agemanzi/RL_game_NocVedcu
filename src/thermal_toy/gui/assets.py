from __future__ import annotations
from pathlib import Path
from functools import lru_cache
from typing import Tuple, Optional
from PIL import Image, ImageTk

def _candidate_dirs() -> list[Path]:
    """Search order for assets/images directory."""
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "assets" / "images",
        here.parents[3] / "assets" / "images",   # repo root / assets/images
        here.parents[2] / "assets" / "images",   # fallback
    ]
    return [p for p in candidates if p.exists()]

@lru_cache(maxsize=128)
def load_sprite(name: str, size: Tuple[int, int] | None = None) -> ImageTk.PhotoImage:
    """Load PNG by stem; optional resize to `size`."""
    stem = name if name.lower().endswith(".png") else f"{name}.png"
    path: Optional[Path] = None
    for base in _candidate_dirs():
        p = base / stem
        if p.exists():
            path = p
            break
    img = Image.open(path).convert("RGBA") if path else Image.new("RGBA", (size or (160, 90)), (64, 64, 64, 255))
    if size is not None:
        img = img.resize(size, Image.LANCZOS)
    return ImageTk.PhotoImage(img)

