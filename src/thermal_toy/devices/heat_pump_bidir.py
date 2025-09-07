# src/thermal_toy/devices/heat_pump_bidir.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional
import bisect

from .base import Device, Clamp


def _interp1d(x: Iterable[float], y: Iterable[float]) -> Callable[[float], float]:
    xs = list(map(float, x))
    ys = list(map(float, y))
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Need >=2 points for interpolation.")
    pairs = sorted(zip(xs, ys))
    xs, ys = zip(*pairs)

    def f(v: float) -> float:
        i = bisect.bisect_left(xs, v)
        if i <= 0:
            return float(ys[0])
        if i >= len(xs):
            return float(ys[-1])
        x0, y0 = xs[i - 1], ys[i - 1]
        x1, y1 = xs[i], ys[i]
        w = (v - x0) / (x1 - x0) if x1 != x0 else 0.0
        return float(y0 + w * (y1 - y0))

    return f


@dataclass(frozen=True)
class BiDirectionalHeatPump(Device):
    """
    Bidirectional heat pump with COP/EER as a function of outdoor temp.

      - action ∈ [-1, 1]  (−1 = full COOL, +1 = full HEAT, 0 = idle)
      - P_elec = |action| * pmax_kw
      - q_heat = sign(action) * COP(Tout) * P_elec

    If cop_fn is None, uses affine COP model clamped to [cop_min, cop_max].
    """
    pmax_kw: float
    cop_fn: Optional[Callable[[float], float]] = None
    cop_ref: float = 3.0
    t_ref_c: float = 7.0
    cop_slope_per_degC: float = 0.05
    cop_min: float = 1.5
    cop_max: float = 5.5
    accept_unsigned_action: bool = False
    _clip_bi: Clamp = Clamp(-1.0, 1.0)
    _clip_uni: Clamp = Clamp(0.0, 1.0)

    def _cop(self, t_out_c: float) -> float:
        if self.cop_fn is not None:
            return float(max(0.1, self.cop_fn(t_out_c)))
        raw = self.cop_ref + self.cop_slope_per_degC * (float(t_out_c) - self.t_ref_c)
        return float(min(self.cop_max, max(self.cop_min, raw)))

    def forward(
        self,
        action: float,
        *,
        dt_h: float,
        t_out_c: Optional[float] = None,
        pv_potential_kw: Optional[float] = None,
    ) -> Dict[str, float]:
        if t_out_c is None:
            raise ValueError("BiDirectionalHeatPump.forward requires t_out_c.")
        u = self._clip_uni(action) if self.accept_unsigned_action else self._clip_bi(action)
        if self.accept_unsigned_action:
            u = 2.0 * u - 1.0  # map [0,1] → [-1,1]
        mag = abs(u)
        elec_power_kw = self.pmax_kw * mag
        cop = self._cop(t_out_c)
        q_heat_kw = (1.0 if u >= 0 else -1.0) * cop * elec_power_kw
        return {
            "q_heat_kw": q_heat_kw,            # <0 means cooling
            "elec_load_kw": elec_power_kw,
            "elec_energy_kwh": elec_power_kw * dt_h,
            "mode": "heat" if u > 0 else ("cool" if u < 0 else "idle"),
            "cop": cop,
        }
