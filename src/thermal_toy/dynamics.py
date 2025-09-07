# src/thermal_toy/dynamics.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple
import numpy as np


@dataclass(frozen=True)
class ThermalParams:
    """
    Parameters for the single-zone linear thermal model.

    Units:
      - Temperatures: °C
      - Power: kW
      - Energy: kWh
      - Time step dt_h: hours
      - C_th_kwh_per_degC: kWh per °C (thermal capacitance)
      - U_kw_per_degC: kW per °C (heat loss coefficient)
    """
    dt_h: float
    C_th_kwh_per_degC: float
    U_kw_per_degC: float
    heater_pmax_kw: float
    heater_eff: float = 1.0
    clip_temp_c: Tuple[float, float] = (-10.0, 40.0)


def step_temp(
    T_in_c: float,
    T_out_c: float,
    action_frac: float,
    params: ThermalParams,
) -> Tuple[float, Dict[str, float]]:
    """
    One-step update of indoor temperature using linear heat balance:

      T_{t+1} = T_t + (dt/C) * [ U * (T_out - T_t) + eta * Pmax * a_t ]

    Where:
      a_t ∈ [0,1] is heater fraction,
      Pmax is heater_pmax_kw (electrical),
      eta maps electrical power to thermal power (≈1.0 for resistive heater).

    Returns:
      T_next_c, diagnostics dict
    """
    p = params
    a = float(np.clip(action_frac, 0.0, 1.0))

    # Thermal powers (kW)
    q_loss_kw = p.U_kw_per_degC * (T_out_c - T_in_c)           # negative when inside > outside
    q_heat_kw = p.heater_eff * p.heater_pmax_kw * a            # delivered thermal power

    # Temperature update
    dT = (p.dt_h / p.C_th_kwh_per_degC) * (q_loss_kw + q_heat_kw)
    T_next_c = float(np.clip(T_in_c + dT, p.clip_temp_c[0], p.clip_temp_c[1]))

    # Electrical consumption (kWh in this step)
    elec_power_kw = p.heater_pmax_kw * a
    elec_energy_kwh = elec_power_kw * p.dt_h

    info = {
        "q_loss_kw": q_loss_kw,
        "q_heat_kw": q_heat_kw,
        "elec_power_kw": elec_power_kw,
        "elec_energy_kwh": elec_energy_kwh,
        "dT": dT,
    }
    return T_next_c, info


def steady_state_temp(T_out_c: float, action_frac: float, params: ThermalParams) -> float:
    """
    Steady-state indoor temperature if action and Tout are held constant:

      0 = U*(Tout - T*) + eta*Pmax*a  ⇒  T* = Tout + (eta*Pmax*a)/U
    """
    p = params
    a = float(np.clip(action_frac, 0.0, 1.0))
    if p.U_kw_per_degC <= 0:
        return float(T_out_c)
    T_star = T_out_c + (p.heater_eff * p.heater_pmax_kw * a) / p.U_kw_per_degC
    return float(np.clip(T_star, p.clip_temp_c[0], p.clip_temp_c[1]))


def simulate_profile(
    T0_c: float,
    T_out_c_series: np.ndarray,
    action_frac_series: np.ndarray,
    params: ThermalParams,
) -> Dict[str, np.ndarray]:
    """
    Roll out the model over a full horizon.

    Inputs:
      T0_c: initial indoor temperature (°C)
      T_out_c_series: shape (T,) outdoor temperature series (°C)
      action_frac_series: shape (T,) heater fractions in [0,1]

    Returns dict with arrays shape (T,):
      T_in_c: indoor temperature at each step (post-update)
      elec_power_kw, elec_energy_kwh, q_loss_kw, q_heat_kw
    """
    T_out = np.asarray(T_out_c_series, dtype=np.float32)
    a = np.clip(np.asarray(action_frac_series, dtype=np.float32), 0.0, 1.0)
    assert T_out.shape == a.shape, "T_out and action series must have same shape"

    T = len(T_out)
    T_in = np.empty(T, dtype=np.float32)
    elec_p = np.empty(T, dtype=np.float32)
    elec_e = np.empty(T, dtype=np.float32)
    q_loss = np.empty(T, dtype=np.float32)
    q_heat = np.empty(T, dtype=np.float32)

    T_curr = float(T0_c)
    for t in range(T):
        T_next, info = step_temp(T_curr, float(T_out[t]), float(a[t]), params)
        T_in[t] = T_next
        elec_p[t] = info["elec_power_kw"]
        elec_e[t] = info["elec_energy_kwh"]
        q_loss[t] = info["q_loss_kw"]
        q_heat[t] = info["q_heat_kw"]
        T_curr = T_next

    return {
        "T_in_c": T_in,
        "elec_power_kw": elec_p,
        "elec_energy_kwh": elec_e,
        "q_loss_kw": q_loss,
        "q_heat_kw": q_heat,
    }


__all__ = [
    "ThermalParams",
    "step_temp",
    "steady_state_temp",
    "simulate_profile",
]
