# src/thermal_toy/devices/resistive.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .base import Device, Clamp


@dataclass(frozen=True)
class ResistiveHeater(Device):
    """
    Simple electric resistive heater:
      action ∈ [0,1] → P = action * pmax_kw, q_heat = eff * P
    """
    pmax_kw: float
    eff: float = 1.0
    _clip: Clamp = Clamp(0.0, 1.0)

    def forward(
        self,
        action: float,
        *,
        dt_h: float,
        t_out_c: Optional[float] = None,
        pv_potential_kw: Optional[float] = None,
    ) -> Dict[str, float]:
        a = self._clip(action)
        elec_power_kw = self.pmax_kw * a
        q_heat_kw = self.eff * elec_power_kw
        return {
            "q_heat_kw": q_heat_kw,
            "elec_load_kw": elec_power_kw,
            "elec_energy_kwh": elec_power_kw * dt_h,  # optional diag
            "mode": "heat" if a > 0 else "idle",
        }
