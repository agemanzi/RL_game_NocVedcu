# src/thermal_toy/devices/battery.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .base import Device, Clamp


@dataclass(frozen=True)
class BatteryActuator(Device):
    """
    Battery action → desired charge/discharge powers.

    Two encodings supported:
      1) split actions: pass both a_ch and a_dis ∈ [0,1] (use map_split=True)
      2) signed action: a ∈ [-1,1] (a>0 → charge, a<0 → discharge)

    Plant will project to SOC/power limits; we only set intents.
    """
    p_ch_max_kw: float
    p_dis_max_kw: float
    map_split: bool = False         # if True, expect tuple/list (a_ch, a_dis)
    _clip_bi: Clamp = Clamp(-1.0, 1.0)
    _clip_uni: Clamp = Clamp(0.0, 1.0)

    def forward(
        self,
        action: float | tuple[float, float] | list[float],
        *,
        dt_h: float,
        t_out_c: Optional[float] = None,
        pv_potential_kw: Optional[float] = None,
    ) -> Dict[str, float]:
        if self.map_split:
            a_ch, a_dis = action if isinstance(action, (tuple, list)) else (float(action), 0.0)
            a_ch = self._clip_uni(float(a_ch))
            a_dis = self._clip_uni(float(a_dis))
            # mutual exclusivity preference: keep the larger request
            if a_ch > a_dis:
                a_dis = 0.0
            else:
                a_ch = 0.0
            p_ch = a_ch * self.p_ch_max_kw
            p_dis = a_dis * self.p_dis_max_kw
        else:
            u = self._clip_bi(float(action))
            if u >= 0:
                p_ch = u * self.p_ch_max_kw
                p_dis = 0.0
            else:
                p_ch = 0.0
                p_dis = (-u) * self.p_dis_max_kw

        # Battery affects bus via p_ch/p_dis; do NOT add to elec_load_kw here.
        return {
            "p_batt_ch_kw": p_ch,
            "p_batt_dis_kw": p_dis,
        }
