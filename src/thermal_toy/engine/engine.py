from __future__ import annotations
from typing import Tuple, Optional
import math

from ..io import build_scenario, load_config_yaml
from ..reward import step_reward, comfort_band
from .types import Action, GameState, Obs, TickInfo

class Engine:
    """
    Minimal single-zone engine:
      Tin update via linear balance, HVAC thermal power from u in [-1,1],
      fixed COPs and capacities from config, overridable via `overrides`.
    """
    def __init__(
        self,
        config_yaml_path: str,
        day_csv_path: str,
        *,
        overrides: Optional[dict] = None,
        debug: bool = False,
    ):
        self.scenario, self.th_params, self.rw_params = build_scenario(
            config_yaml_path, day_csv_path, enforce_horizon=False
        )
        cfg = load_config_yaml(config_yaml_path)
        ov = overrides or {}

        # HVAC sizing and COPs (fallbacks keep you running)
        self.q_heat_max_kw = float(ov.get("hp_q_heat_max_kw_th",
                                 cfg.get("hp_q_heat_max_kw_th", cfg.get("heater_pmax_kw", 3.0))))
        self.q_cool_max_kw = float(ov.get("hp_q_cool_max_kw_th",
                                 cfg.get("hp_q_cool_max_kw_th", self.q_heat_max_kw)))
        self.cop_heat = float(ov.get("hp_cop_heat", cfg.get("hp_cop_heat", 3.0)))
        self.cop_cool = float(ov.get("hp_cop_cool", cfg.get("hp_cop_cool", 3.0)))

        self.debug = bool(debug)

        self.band_L, self.band_U = comfort_band(
            float(self.scenario.T_set_c), float(self.scenario.comfort_width_c)
        )

        self._state = GameState(
            k=0,
            Tin_c=float(self.scenario.T_in0_c),
            soc=None,
            cum_energy_cost_eur=0.0,
            cum_comfort_penalty_eur=0.0,
            cum_reward=0.0,
        )

    # ---- public API ----
    def reset(self) -> TickInfo:
        self._state.k = 0
        self._state.Tin_c = float(self.scenario.T_in0_c)
        self._state.cum_energy_cost_eur = 0.0
        self._state.cum_comfort_penalty_eur = 0.0
        self._state.cum_reward = 0.0
        if self.debug:
            print("[Engine] reset: Tin0=%.2f" % self._state.Tin_c)
        return self._build_tickinfo(last_elec_energy_kwh=0.0, q_heat_kw=0.0, q_loss_kw=0.0, elec_power_kw=0.0, reward=0.0)

    def step(self, action: Action) -> TickInfo:
        k = self._state.k
        T = self.scenario.T
        truncated = k >= T - 1
        terminated = False

        # Exogenous at k
        dt = float(self.scenario.dt_h)
        Tout = float(self.scenario.t_out_c[k])
        price = float(self.scenario.price_eur_per_kwh[k])

        # Map action -> thermal power (kW_th), clipped
        u = float(max(-1.0, min(1.0, action.hvac_u)))
        if u >= 0:
            q_hvac_kw = u * self.q_heat_max_kw
            elec_power_kw = q_hvac_kw / max(self.cop_heat, 1e-6)
        else:
            q_hvac_kw = u * self.q_cool_max_kw  # negative thermal (cooling)
            elec_power_kw = (-q_hvac_kw) / max(self.cop_cool, 1e-6)

        # Thermal balance
        C = float(self.th_params.C_th_kwh_per_degC)
        U = float(self.th_params.U_kw_per_degC)
        Tin = float(self._state.Tin_c)
        q_loss_kw = U * (Tout - Tin)
        dT = (dt / max(C, 1e-9)) * (q_loss_kw + q_hvac_kw)
        Tin_next = float(Tin + dT)
        lo, hi = self.th_params.clip_temp_c
        Tin_next = float(min(hi, max(lo, Tin_next)))

        # Energy cost & reward
        elec_energy_kwh = elec_power_kw * dt
        r, info_r = step_reward(
            t_in_c=Tin_next,
            t_set_c=float(self.scenario.T_set_c),
            comfort_width_c=float(self.scenario.comfort_width_c),
            price_eur_per_kwh=price,
            elec_energy_kwh=elec_energy_kwh,
            params=self.rw_params,
        )

        # Update state
        self._state.Tin_c = Tin_next
        self._state.k = min(k + 1, T - 1)
        self._state.cum_energy_cost_eur += info_r["cost_eur_step"]
        self._state.cum_comfort_penalty_eur += info_r["comfort_penalty_eur_step"]
        self._state.cum_reward += r

        if self.debug:
            print(f"[Engine] k={k} u={u:+.2f} Tout={Tout:.2f} Tin={Tin:.2f}->{Tin_next:.2f} "
                  f"q={q_hvac_kw:+.2f}kW P={elec_power_kw:.2f}kW price={price:.3f}€ J={-r:.3f}€")
        if self.debug:
            print("=" * 60)
            
            print(f"[Engine] Step {k} | u={u:+.2f}")
            print(f"  Tin: {Tin:.2f}°C → {Tin_next:.2f}°C | dT = {dT:.4f}°C")
            print(f"  Tout: {Tout:.2f}°C | q_loss = {q_loss_kw:+.2f} kW | q_hvac = {q_hvac_kw:+.2f} kW")
            print(f"  Elec: {elec_power_kw:.2f} kW → {elec_energy_kwh:.3f} kWh | Price = {price:.3f} €/kWh")
            print(f"  Reward: {r:+.4f} | Cost: {info_r['cost_eur_step']:.4f} | Penalty: {info_r['comfort_penalty_eur_step']:.4f}")

        return self._build_tickinfo(
            last_elec_energy_kwh=elec_energy_kwh,
            q_heat_kw=q_hvac_kw,
            q_loss_kw=q_loss_kw,
            elec_power_kw=elec_power_kw,
            reward=r,
            terminated=terminated,
            truncated=truncated,
        )

    # ---- helpers ----
    def _build_obs(self) -> Obs:
        k = self._state.k
        dt = float(self.scenario.dt_h)
        hour = (k * dt) % 24.0
        return Obs(
            Tin_c=float(self._state.Tin_c),
            Tout_c=float(self.scenario.t_out_c[k]),
            price_eur_per_kwh=float(self.scenario.price_eur_per_kwh[k]),
            hour_frac=hour,
            comfort_L_c=float(self.band_L),
            comfort_U_c=float(self.band_U),
            dt_h=dt,
        )

    def _build_tickinfo(
        self,
        *,
        last_elec_energy_kwh: float,
        q_heat_kw: float,
        q_loss_kw: float,
        elec_power_kw: float,
        reward: float,
        terminated: bool = False,
        truncated: bool = False,
    ) -> TickInfo:
        obs = self._build_obs()
        info = {
            "t": int(self._state.k),
            "Tin_c": float(self._state.Tin_c),
            "Tout_c": float(obs.Tout_c),
            "price_eur_per_kwh": float(obs.price_eur_per_kwh),
            "dt_h": float(obs.dt_h),
            "q_heat_kw": float(q_heat_kw),
            "q_loss_kw": float(q_loss_kw),
            "elec_power_kw": float(elec_power_kw),
            "elec_energy_kwh": float(last_elec_energy_kwh),
            "cum_energy_cost_eur": float(self._state.cum_energy_cost_eur),
            "cum_comfort_penalty_eur": float(self._state.cum_comfort_penalty_eur),
            "cum_reward": float(self._state.cum_reward),
            "comfort_L_c": float(self.band_L),
            "comfort_U_c": float(self.band_U),
        }
        return TickInfo(
            obs=obs,
            info=info,
            reward=float(reward),
            terminated=terminated,
            truncated=truncated,
            state=self._state,
        )
