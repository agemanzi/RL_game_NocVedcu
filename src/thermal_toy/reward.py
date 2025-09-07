# src/thermal_toy/reward.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple
import numpy as np


@dataclass(frozen=True)
class RewardParams:
    """
    Reward/cost parameters and constants.

    Units:
      - Temperatures: °C
      - Energy price: €/kWh
      - Energy: kWh
      - lambda_temp_eur_per_degCh: €/ (°C · h)
      - dt_h: hours per step
    """
    lambda_temp_eur_per_degCh: float = 2.0
    dt_h: float = 0.25
    # For observation scaling only (not used in cost calculation):
    price_norm_ref_eur_per_kwh: float = 0.5


def comfort_band(t_set_c: float, width_c: float) -> Tuple[float, float]:
    """
    Compute comfort band [L, U] around setpoint with given width.
    """
    half = 0.5 * float(width_c)
    L = float(t_set_c) - half
    U = float(t_set_c) + half
    return L, U


def comfort_slacks(
    t_in_c: float,
    t_set_c: float,
    width_c: float,
) -> Tuple[float, float, float, float]:
    """
    Return (s_below, s_above, L, U) where slacks are ≥0 and zero inside [L, U].
    """
    L, U = comfort_band(t_set_c, width_c)
    s_below = max(0.0, L - float(t_in_c))
    s_above = max(0.0, float(t_in_c) - U)
    return s_below, s_above, L, U


def step_cost_eur(price_eur_per_kwh: float, elec_energy_kwh: float) -> float:
    """
    Energy cost for this step in euros.
    """
    return float(price_eur_per_kwh) * float(elec_energy_kwh)


def step_reward(
    t_in_c: float,
    t_set_c: float,
    comfort_width_c: float,
    price_eur_per_kwh: float,
    elec_energy_kwh: float,
    params: RewardParams,
) -> Tuple[float, Dict[str, float]]:
    """
    Compute per-step reward and logging info.

    Objective to minimize:
        J_t = energy_cost + lambda_T * (s_below + s_above) * dt

    Reward for RL:
        r_t = -J_t
    """
    s_below, s_above, L, U = comfort_slacks(t_in_c, t_set_c, comfort_width_c)
    energy_cost = step_cost_eur(price_eur_per_kwh, elec_energy_kwh)
    comfort_penalty = params.lambda_temp_eur_per_degCh * (s_below + s_above) * params.dt_h
    obj_step = energy_cost + comfort_penalty
    reward = -obj_step

    info = {
        "comfort_L_c": L,
        "comfort_U_c": U,
        "s_temp_below_c": s_below,
        "s_temp_above_c": s_above,
        "cost_eur_step": energy_cost,
        "comfort_penalty_eur_step": comfort_penalty,
        "objective_eur_step": obj_step,
    }
    return reward, info


# -------- Vectorized helpers (optional) --------

def rollout_costs_and_penalties(
    T_in_c: np.ndarray,
    T_set_c: float,
    comfort_width_c: float,
    price_eur_per_kwh: np.ndarray,
    elec_energy_kwh: np.ndarray,
    params: RewardParams,
) -> Dict[str, np.ndarray]:
    """
    Vectorized computation over a full horizon.

    Returns dict with arrays:
      - energy_cost_eur
      - s_temp_below_c, s_temp_above_c
      - comfort_penalty_eur
      - objective_eur
      - reward
    """
    T_in = np.asarray(T_in_c, dtype=np.float32)
    price = np.asarray(price_eur_per_kwh, dtype=np.float32)
    e_kwh = np.asarray(elec_energy_kwh, dtype=np.float32)
    assert T_in.shape == price.shape == e_kwh.shape, "All series must align"

    L, U = comfort_band(T_set_c, comfort_width_c)
    s_below = np.maximum(0.0, L - T_in)
    s_above = np.maximum(0.0, T_in - U)

    energy_cost = price * e_kwh
    comfort_pen = params.lambda_temp_eur_per_degCh * (s_below + s_above) * params.dt_h
    obj = energy_cost + comfort_pen
    rew = -obj

    return {
        "energy_cost_eur": energy_cost.astype(np.float32),
        "s_temp_below_c": s_below.astype(np.float32),
        "s_temp_above_c": s_above.astype(np.float32),
        "comfort_penalty_eur": comfort_pen.astype(np.float32),
        "objective_eur": obj.astype(np.float32),
        "reward": rew.astype(np.float32),
    }


__all__ = [
    "RewardParams",
    "comfort_band",
    "comfort_slacks",
    "step_cost_eur",
    "step_reward",
    "rollout_costs_and_penalties",
]
