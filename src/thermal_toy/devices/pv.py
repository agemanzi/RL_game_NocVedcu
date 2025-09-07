# src/thermal_toy/devices/pv.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .base import Device, Clamp


@dataclass(frozen=True)
class PVInverter(Device):
    """
    PV curtailment controller:
      action ∈ [0,1] scales the available pv_potential_kw.
    """
    _clip: Clamp = Clamp(0.0, 1.0)

    def forward(
        self,
        action: float,
        *,
        dt_h: float,
        t_out_c: Optional[float] = None,
        pv_potential_kw: Optional[float] = None,
    ) -> Dict[str, float]:
        if pv_potential_kw is None:
            pv_potential_kw = 0.0
        a = self._clip(action)
        pv_used = max(0.0, a * float(pv_potential_kw))
        return {"pv_used_kw": pv_used}
