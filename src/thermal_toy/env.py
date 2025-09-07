# src/thermal_toy/env.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from .io import build_scenario, set_global_seed, Scenario
from .dynamics import ThermalParams, step_temp
from .reward import RewardParams, step_reward, comfort_band


@dataclass
class EnvConfig:
    config_yaml_path: str
    day_csv_path: str
    # Observation scaling constants (purely for normalization)
    temp_scale: float = 30.0  # divide temps by this in obs
    use_next_exogenous: bool = True  # obs after step uses exogenous at t+1
    seed: Optional[int] = None


class ThermalHeaterEnv(gym.Env):
    """
    Minimal single-zone heater environment.

    - Action: a_t in [0,1] (heater fraction).
    - State: indoor temperature (continuous).
    - Exogenous per step: Tout (°C), price (€/kWh), dt_h (hours).
    - Reward: negative of (energy cost + comfort penalty).

    Termination: never (soft constraints). Truncation at end of horizon.
    Render: 'ansi' one-line HUD.
    """

    metadata = {"render_modes": ["ansi"], "render_fps": 4}

    def __init__(self, env_cfg: EnvConfig):
        super().__init__()
        self.env_cfg = env_cfg

        # Seed everything deterministic (torch can be seeded elsewhere)
        set_global_seed(env_cfg.seed)

        # Load scenario + params
        self.scenario, self.th_params, self.rw_params = build_scenario(
            env_cfg.config_yaml_path, env_cfg.day_csv_path, enforce_horizon=True
        )

        # Cache exogenous series
        self.T = self.scenario.T
        self.dt_h = self.scenario.dt_h
        self.t_out = self.scenario.t_out_c.astype(np.float32)
        self.price = self.scenario.price_eur_per_kwh.astype(np.float32)

        # Comfort config
        self.T_set = float(self.scenario.T_set_c)
        self.band_width = float(self.scenario.comfort_width_c)
        self.band_L, self.band_U = comfort_band(self.T_set, self.band_width)

        # Obs/action spaces
        self.temp_scale = float(env_cfg.temp_scale)
        self.price_ref = max(float(self.rw_params.price_norm_ref_eur_per_kwh), 1e-6)

        # obs = [Tin/scale, Tout/scale, price/price_ref, sin_hr, cos_hr, L/scale, U/scale]
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(7,), dtype=np.float32
        )
        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32)

        # Runtime
        self._k: int = 0
        self._Tin: float = float(self.scenario.T_in0_c)
        self._last_info: Dict[str, Any] = {}
        self._cum_energy_cost = 0.0
        self._cum_comfort_pen = 0.0
        self._cum_reward = 0.0
        self._render_buffer: Optional[str] = None
        self._use_next = bool(env_cfg.use_next_exogenous)

    # ------------- Gym API -------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        if seed is not None:
            set_global_seed(seed)
        self._k = 0
        self._Tin = float(self.scenario.T_in0_c)
        self._cum_energy_cost = 0.0
        self._cum_comfort_pen = 0.0
        self._cum_reward = 0.0
        self._last_info = {}

        obs = self._build_obs(index=self._k if self._use_next else 0, Tin=self._Tin)
        info = {"t": 0, "Tin_c": self._Tin}
        return obs, info

    def step(self, action):
        # --- Bound & unpack action
        a = float(np.clip(np.asarray(action, dtype=np.float32).reshape(-1)[0], 0.0, 1.0))

        # --- Use exogenous at current index k
        k = self._k
        Tout = float(self.t_out[k])
        price = float(self.price[k])

        # --- Dynamics: update temperature with chosen action
        Tin_next, dyn = step_temp(
            T_in_c=self._Tin,
            T_out_c=Tout,
            action_frac=a,
            params=self.th_params,
        )

        # --- Reward from (Tin_next, price at k)
        r, info_r = step_reward(
            t_in_c=Tin_next,
            t_set_c=self.T_set,
            comfort_width_c=self.band_width,
            price_eur_per_kwh=price,
            elec_energy_kwh=dyn["elec_energy_kwh"],
            params=self.rw_params,
        )

        # --- Accounting
        self._Tin = Tin_next
        self._k += 1
        self._cum_energy_cost += info_r["cost_eur_step"]
        self._cum_comfort_pen += info_r["comfort_penalty_eur_step"]
        self._cum_reward += r

        # --- Episode end?
        truncated = self._k >= self.T
        terminated = False  # soft constraints only, never terminal early

        # --- Next observation index
        obs_index = min(self._k, self.T - 1) if self._use_next else max(self._k - 1, 0)
        obs = self._build_obs(index=obs_index, Tin=self._Tin)

        # --- Info dict (debuggable)
        info = {
            "t": k,
            "action_frac": a,
            "Tin_c": Tin_next,
            "Tout_c": Tout,
            "price_eur_per_kwh": price,
            "elec_power_kw": dyn["elec_power_kw"],
            "elec_energy_kwh": dyn["elec_energy_kwh"],
            "q_loss_kw": dyn["q_loss_kw"],
            "q_heat_kw": dyn["q_heat_kw"],
            "cost_eur_step": info_r["cost_eur_step"],
            "comfort_penalty_eur_step": info_r["comfort_penalty_eur_step"],
            "objective_eur_step": info_r["objective_eur_step"],
            "cum_energy_cost_eur": self._cum_energy_cost,
            "cum_comfort_penalty_eur": self._cum_comfort_pen,
            "cum_reward": self._cum_reward,
            "comfort_L_c": self.band_L,
            "comfort_U_c": self.band_U,
        }
        self._last_info = info

        return obs, r, terminated, truncated, info

    def render(self):
        # ANSI single-line HUD
        if self._last_info is None or "t" not in self._last_info:
            return ""
        i = self._last_info
        line = (
            f"t={i['t']:02d} "
            f"T_in={i['Tin_c']:.2f}°C "
            f"T_out={i['Tout_c']:.2f}°C "
            f"a={i['action_frac']:.2f} "
            f"P={i['elec_power_kw']:.2f}kW "
            f"price={i['price_eur_per_kwh']:.3f}€/kWh "
            f"cost={i['cost_eur_step']:.3f}€ "
            f"pen={i['comfort_penalty_eur_step']:.3f}€ "
            f"J={i['objective_eur_step']:.3f}€ "
            f"Σcost={i['cum_energy_cost_eur']:.2f}€ "
            f"Σpen={i['cum_comfort_penalty_eur']:.2f}€"
        )
        self._render_buffer = line
        return line

    def close(self):
        return

    # ------------- Helpers -------------

    def _build_obs(self, index: int, Tin: float) -> np.ndarray:
        # Exogenous at index
        Tout = float(self.t_out[index])
        price = float(self.price[index])

        # Time features
        hour = (index * self.dt_h) % 24.0
        ang = 2.0 * math.pi * (hour / 24.0)
        sin_h = math.sin(ang)
        cos_h = math.cos(ang)

        obs = np.array(
            [
                float(Tin) / self.temp_scale,
                Tout / self.temp_scale,
                price / self.price_ref,
                sin_h,
                cos_h,
                self.band_L / self.temp_scale,
                self.band_U / self.temp_scale,
            ],
            dtype=np.float32,
        )
        return obs


__all__ = ["ThermalHeaterEnv", "EnvConfig"]
