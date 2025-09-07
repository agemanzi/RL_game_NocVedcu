# src/thermal_toy/devices/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Protocol


class Device(Protocol):
    """
    Minimal protocol for a device contributing to plant Ports.
    Implement forward() to return a dict with any of:
      - "q_heat_kw"       : + into room, − if cooling (kW_th)
      - "elec_load_kw"    : electrical draw (kW)
      - "p_batt_ch_kw"    : battery charge power (kW, ≥0)
      - "p_batt_dis_kw"   : battery discharge power (kW, ≥0)
      - "pv_used_kw"      : PV power used on AC bus (kW, ≥0)
      plus optional diagnostics (e.g., "mode", "cop").
    """
    def forward(
        self,
        action: float,
        *,
        dt_h: float,
        t_out_c: Optional[float] = None,
        pv_potential_kw: Optional[float] = None,
    ) -> Dict[str, float]:
        ...


@dataclass(frozen=True)
class Clamp:
    """Utility to clamp actions to a range."""
    lo: float
    hi: float

    def __call__(self, x: float) -> float:
        return max(self.lo, min(self.hi, float(x)))
