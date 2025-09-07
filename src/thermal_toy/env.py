# src/thermal_toy/env.py
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from .io import build_scenario, set_global_seed
from .dynamics import (
    ThermalParams,
    BatteryParams,
    ElectricLimits,
    PlantState,
    Exogenous,
    Ports,
    plant_step_multi,
)
from .reward import RewardParams, step_reward, comfort_band
from .devices import make_devices
from .devices.resistive import ResistiveHeater
from .devices.heat_pump_bidir import BiDirectionalHeatPump
from .devices.battery import BatteryActuator
from .devices.pv import PVInverter


@dataclass
class EnvConfig:
    config_yaml_path: str
    day_csv_path: str
    # Devices: list of {"kind": "...", <kwargs>...}
    devices: List[Dict[str, Any]] = field(default_factory=lambda: [{"kind": "resistive", "pmax_kw": 3.0}])

    # Optional plant-side parameters
    battery_params: Optional[BatteryParams] = None
    electric_limits: Optional[ElectricLimits] = None
    init_soc: Optional[float] = None  # only used if battery_params is provided

    # Observation scaling / behavior
    temp_scale: float = 30.0
    use_next_exogenous: bool = True
    seed: Optional[int] = None


class ThermalPlantEnv(gym.Env):
    """
    Single-zone thermal environment with a modular device stack.

    - Action: concatenation of per-device actions (order = provided devices list)
    - State: indoor temperature (and optional battery SOC internally)
    - Exogenous per step: Tout (°C), price (€/kWh); (base_load, pv_potential) default to 0
    - Reward: negative of (energy cost + comfort penalty), with energy cost = price * grid_import_kWh
    """

    metadata = {"render_modes": ["ansi"], "render_fps": 4}

    def __init__(self, env_cfg: EnvConfig):
        super().__init__()
        self.env_cfg = env_cfg
        set_global_seed(env_cfg.seed)

        # Load scenario + params
        self.scenario, self.th_params, self.rw_params = build_scenario(
            env_cfg.config_yaml_path, env_cfg.day_csv_path, enforce_horizon=True
        )

        # Devices
        self.devices = make_devices(env_cfg.devices)

        # Action space composition
        self._act_slices, lows, highs = self._build_action_space(self.devices)
        self.action_space = spaces.Box(low=np.array(lows, dtype=np.float32),
                                       high=np.array(highs, dtype=np.float32),
                                       dtype=np.float32)

        # Cache exogenous series
        self.T = self.scenario.T
        self.dt_h = self.scenario.dt_h
        self.t_out = self.scenario.t_out_c.astype(np.float32)
        self.price = self.scenario.price_eur_per_kwh.astype(np.float32)
        self.base_load = np.zeros(self.T, dtype=np.float32)        # placeholder (extend later)
        self.pv_potential = np.zeros(self.T, dtype=np.float32)     # placeholder (extend later)

        # Comfort config
        self.T_set = float(self.scenario.T_set_c)
        self.band_width = float(self.scenario.comfort_width_c)
        self.band_L, self.band_U = comfort_band(self.T_set, self.band_width)

        # Obs scaling
        self.temp_scale = float(env_cfg.temp_scale)
        self.price_ref = max(float(self.rw_params.price_norm_ref_eur_per_kwh), 1e-6)

        # obs = [Tin/scale, Tout/scale, price/price_ref, sin_hr, cos_hr, L/scale, U/scale]
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(7,), dtype=np.float32)

        # Runtime state
        self._k: int = 0
        self._Tin: float = float(self.scenario.T_in0_c)
        self._soc: Optional[float] = None
        if self.env_cfg.battery_params is not None:
            # initialize SOC if battery present
            self._soc = float(self.env_cfg.init_soc if self.env_cfg.init_soc is not None else 0.5)

        self._last_info: Dict[str, Any] = {}
        self._cum_energy_cost = 0.0
        self._cum_comfort_pen = 0.0
        self._cum_reward = 0.0
        self._use_next = bool(env_cfg.use_next_exogenous)

    # ------------- Gym API -------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        if seed is not None:
            set_global_seed(seed)
        self._k = 0
        self._Tin = float(self.scenario.T_in0_c)
        if self.env_cfg.battery_params is not None:
            self._soc = float(self.env_cfg.init_soc if self.env_cfg.init_soc is not None else 0.5)
        else:
            self._soc = None

        self._cum_energy_cost = 0.0
        self._cum_comfort_pen = 0.0
        self._cum_reward = 0.0
        self._last_info = {}

        obs = self._build_obs(index=self._k if self._use_next else 0, Tin=self._Tin)
        info = {"t": 0, "Tin_c": self._Tin}
        return obs, info

    def step(self, action):
        a_vec = np.asarray(action, dtype=np.float32).reshape(-1)
        # Clamp to action space
        a_vec = np.minimum(np.maximum(a_vec, self.action_space.low), self.action_space.high)
        k = self._k

        Tout = float(self.t_out[k])
        price = float(self.price[k])
        base_kw = float(self.base_load[k])
        pv_pot_kw = float(self.pv_potential[k])

        # Accumulate device contributions to Ports
        ports = Ports()
        for (i0, i1), dev in zip(self._act_slices, self.devices):
            sub = a_vec[i0:i1]
            act = float(sub[0]) if len(sub) == 1 else tuple(map(float, sub))
            out = dev.forward(
                act, dt_h=self.dt_h, t_out_c=Tout, pv_potential_kw=pv_pot_kw
            )
            # Sum known keys
            ports = Ports(
                q_heat_kw=ports.q_heat_kw + float(out.get("q_heat_kw", 0.0)),
                elec_load_kw=ports.elec_load_kw + float(out.get("elec_load_kw", 0.0)),
                p_batt_ch_kw=ports.p_batt_ch_kw + float(out.get("p_batt_ch_kw", 0.0)),
                p_batt_dis_kw=ports.p_batt_dis_kw + float(out.get("p_batt_dis_kw", 0.0)),
                pv_used_kw=ports.pv_used_kw + float(out.get("pv_used_kw", 0.0)),
            )

        # Plant step
        state = PlantState(Tin_c=self._Tin, soc=self._soc)
        exog = Exogenous(Tout_c=Tout, base_load_kw=base_kw, pv_potential_kw=pv_pot_kw)
        next_state, info_p = plant_step_multi(
            state,
            exog,
            ports,
            self.th_params,
            bat=self.env_cfg.battery_params,
            limits=self.env_cfg.electric_limits,
        )

        Tin_next = float(next_state.Tin_c)
        self._soc = next_state.soc

        # Use GRID IMPORT energy for billing
        elec_import_kwh = float(info_p["g_import_kwh"])

        r, info_r = step_reward(
            t_in_c=Tin_next,
            t_set_c=self.T_set,
            comfort_width_c=self.band_width,
            price_eur_per_kwh=price,
            elec_energy_kwh=elec_import_kwh,
            params=self.rw_params,
        )

        # Accounting
        self._Tin = Tin_next
        self._k += 1
        self._cum_energy_cost += info_r["cost_eur_step"]
        self._cum_comfort_pen += info_r["comfort_penalty_eur_step"]
        self._cum_reward += r

        truncated = self._k >= self.T
        terminated = False

        obs_index = min(self._k, self.T - 1) if self._use_next else max(self._k - 1, 0)
        obs = self._build_obs(index=obs_index, Tin=self._Tin)

        # Info dict
        info = {
            "t": k,
            "Tin_c": Tin_next,
            "Tout_c": Tout,
            "price_eur_per_kwh": price,
            # Ports & plant diagnostics
            "q_heat_kw": info_p["q_heat_kw"],
            "q_loss_kw": info_p["q_loss_kw"],
            "elec_load_kw": info_p["elec_load_kw"],
            "pv_used_kw": info_p["pv_used_kw"],
            "p_batt_ch_kw": info_p["p_batt_ch_kw"],
            "p_batt_dis_kw": info_p["p_batt_dis_kw"],
            "g_import_kw": info_p["g_import_kw"],
            "g_export_kw": info_p["g_export_kw"],
            "g_import_kwh": info_p["g_import_kwh"],
            "g_export_kwh": info_p["g_export_kwh"],
            # Costs
            "cost_eur_step": info_r["cost_eur_step"],
            "comfort_penalty_eur_step": info_r["comfort_penalty_eur_step"],
            "objective_eur_step": info_r["objective_eur_step"],
            "cum_energy_cost_eur": self._cum_energy_cost,
            "cum_comfort_penalty_eur": self._cum_comfort_pen,
            "cum_reward": self._cum_reward,
            "comfort_L_c": self.band_L,
            "comfort_U_c": self.band_U,
            "soc": self._soc,
        }
        self._last_info = info
        return obs, r, terminated, truncated, info

    def render(self):
        if not self._last_info or "t" not in self._last_info:
            return ""
        i = self._last_info
        return (
            f"t={i['t']:02d} "
            f"T_in={i['Tin_c']:.2f}°C "
            f"T_out={i['Tout_c']:.2f}°C "
            f"P_grid={i['g_import_kw']:.2f}kW "
            f"price={i['price_eur_per_kwh']:.3f}€/kWh "
            f"cost={i['cost_eur_step']:.3f}€ "
            f"pen={i['comfort_penalty_eur_step']:.3f}€ "
            f"J={i['objective_eur_step']:.3f}€ "
            f"Σcost={i['cum_energy_cost_eur']:.2f}€ "
            f"Σpen={i['cum_comfort_penalty_eur']:.2f}€"
        )

    # ------------- Helpers -------------

    def _build_obs(self, index: int, Tin: float) -> np.ndarray:
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

    def _build_action_space(self, devices: List[Any]) -> Tuple[List[Tuple[int, int]], List[float], List[float]]:
        """
        Determine per-device action dims and overall bounds.
        Returns:
          - list of (start, end) index slices per device
          - lows, highs arrays
        """
        slices: List[Tuple[int, int]] = []
        lows: List[float] = []
        highs: List[float] = []
        cursor = 0
        for dev in devices:
            if isinstance(dev, BatteryActuator) and dev.map_split:
                dim = 2
                lo, hi = [0.0, 0.0], [1.0, 1.0]
            elif isinstance(dev, BiDirectionalHeatPump) and not dev.accept_unsigned_action:
                dim = 1
                lo, hi = [-1.0], [1.0]
            else:
                dim = 1
                lo, hi = [0.0], [1.0]
            slices.append((cursor, cursor + dim))
            lows.extend(lo)
            highs.extend(hi)
            cursor += dim
        return slices, lows, highs


__all__ = ["ThermalPlantEnv", "EnvConfig"]
