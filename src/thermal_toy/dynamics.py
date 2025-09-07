# src/thermal_toy/dynamics.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import numpy as np


# -------------------------
# Thermal (room) parameters
# -------------------------
@dataclass(frozen=True)
class ThermalParams:
    """
    Single-zone linear thermal PLANT parameters.

    Units:
      - Temperatures: °C
      - Power: kW
      - Energy: kWh
      - dt_h: hours per step
      - C_th_kwh_per_degC: kWh per °C (thermal capacitance)
      - U_kw_per_degC:  kW per °C (heat loss coefficient)
    """
    dt_h: float
    C_th_kwh_per_degC: float
    U_kw_per_degC: float
    clip_temp_c: Tuple[float, float] = (-10.0, 40.0)

    # Legacy heater fields (kept for backward compatibility with step_temp)
    heater_pmax_kw: float = 3.0
    heater_eff: float = 1.0


# -------------------------
# Battery parameters (optional)
# -------------------------
@dataclass(frozen=True)
class BatteryParams:
    """
    Simple battery model:
      - Energy capacity (kWh)
      - Charge/discharge power limits (kW)
      - Round-trip efficiencies
      - SOC bounds (0..1)
    """
    e_kwh: float = 0.0
    p_ch_max_kw: float = 0.0
    p_dis_max_kw: float = 0.0
    eta_ch: float = 0.95
    eta_dis: float = 0.95
    soc_min: float = 0.1
    soc_max: float = 0.9


# -------------------------
# Grid/electric limits (optional)
# -------------------------
@dataclass(frozen=True)
class ElectricLimits:
    gmax_kw: float = 1e9       # effectively unbounded by default
    allow_export: bool = True  # net metering/export flag


# -------------------------
# Plant state, exogenous, and modular "ports"
# -------------------------
@dataclass
class PlantState:
    """States of the plant that evolve step-to-step."""
    Tin_c: float                 # indoor temperature (°C)
    soc: Optional[float] = None  # battery SOC (0..1), None if no battery


@dataclass(frozen=True)
class Exogenous:
    """External signals for the current step."""
    Tout_c: float                  # outdoor temperature (°C)
    base_load_kw: float = 0.0      # non-controllable electric load (kW)
    pv_potential_kw: float = 0.0   # available PV AC power (kW); controller may curtail


@dataclass(frozen=True)
class Ports:
    """
    Device "ports" into the plant for THIS STEP ONLY.
    Think of them as a small signal bus any device can write to:

      - q_heat_kw:     total thermal power added to the room (kW_th); <0 ⇒ cooling
      - elec_load_kw:  total electric load from devices (kW) (HP compressor, e-heater, etc.)
      - p_batt_ch_kw:  battery charge power from grid/bus (kW)   (≥0)
      - p_batt_dis_kw: battery discharge power to bus (kW)      (≥0)
      - pv_used_kw:    PV power injected to bus/loads (kW) (≤ exog.pv_potential_kw)

    Convention: all powers are non-negative except q_heat_kw may be signed.
    Netting happens in plant_step_multi().
    """
    q_heat_kw: float = 0.0
    elec_load_kw: float = 0.0
    p_batt_ch_kw: float = 0.0
    p_batt_dis_kw: float = 0.0
    pv_used_kw: float = 0.0


# -------------------------
# Helpers
# -------------------------
def _battery_project(
    p_ch_kw: float,
    p_dis_kw: float,
    soc: float,
    th: ThermalParams,
    bat: BatteryParams,
) -> Tuple[float, float, float, Dict[str, float]]:
    """
    Enforce non-negativity, power limits, exclusivity, and SOC bounds.
    Returns (p_ch_kw, p_dis_kw, soc_next, info).
    """
    dt = th.dt_h
    # clip to [0, max]
    p_ch = float(np.clip(p_ch_kw, 0.0, bat.p_ch_max_kw))
    p_dis = float(np.clip(p_dis_kw, 0.0, bat.p_dis_max_kw))

    # exclusivity: keep only the larger side this step
    if p_ch > 0.0 and p_dis > 0.0:
        if p_ch >= p_dis:
            p_dis = 0.0
        else:
            p_ch = 0.0

    soc_prev = float(np.clip(soc, 0.0, 1.0))
    # raw update
    denomE = max(bat.e_kwh, 1e-9)
    soc_next = soc_prev + (bat.eta_ch * p_ch * dt) / denomE \
                        - (p_dis * dt) / (bat.eta_dis * denomE)

    # enforce SOC bounds by scaling down p_ch / p_dis if needed
    if soc_next > bat.soc_max and p_ch > 0.0:
        over = soc_next - bat.soc_max
        denom = (bat.eta_ch * p_ch * dt) / denomE
        s = 0.0 if denom <= 0 else max(0.0, 1.0 - over / denom)
        p_ch *= s
        soc_next = soc_prev + (bat.eta_ch * p_ch * dt) / denomE - (p_dis * dt) / (bat.eta_dis * denomE)

    if soc_next < bat.soc_min and p_dis > 0.0:
        under = bat.soc_min - soc_next
        denom = (p_dis * dt) / (bat.eta_dis * denomE)
        s = 0.0 if denom <= 0 else max(0.0, 1.0 - under / denom)
        p_dis *= s
        soc_next = soc_prev + (bat.eta_ch * p_ch * dt) / denomE - (p_dis * dt) / (bat.eta_dis * denomE)

    soc_next = float(np.clip(soc_next, bat.soc_min, bat.soc_max))
    info = {"p_batt_ch_kw_proj": p_ch, "p_batt_dis_kw_proj": p_dis, "soc_next": soc_next}
    return p_ch, p_dis, soc_next, info


def _thermal_step(Tin_c: float, Tout_c: float, q_heat_kw: float, th: ThermalParams) -> Tuple[float, Dict[str, float]]:
    """Room temperature update with delivered heat (device-agnostic)."""
    q_loss_kw = th.U_kw_per_degC * (Tout_c - Tin_c)           # negative if T_in > T_out
    dT = (th.dt_h / th.C_th_kwh_per_degC) * (q_loss_kw + float(q_heat_kw))
    T_next_c = float(np.clip(Tin_c + dT, th.clip_temp_c[0], th.clip_temp_c[1]))
    return T_next_c, {"q_loss_kw": q_loss_kw, "q_heat_kw": float(q_heat_kw), "dT": dT}


# -------------------------
# Main multi-device plant step
# -------------------------
def plant_step_multi(
    state: PlantState,
    exog: Exogenous,
    ports: Ports,
    th: ThermalParams,
    bat: Optional[BatteryParams] = None,
    limits: Optional[ElectricLimits] = None,
) -> Tuple[PlantState, Dict[str, float]]:
    """
    Single-zone plant with modular devices on an electric/thermal bus.

    Inputs (per-step):
      - state: current Tin and optional SOC
      - exog:  Tout, base load, PV potential
      - ports: device contributions (q_heat, elec load, batt ch/dis, pv used)

    Evolution:
      - Tin via thermal balance
      - Battery SOC via bucket model (optional)
      - Electric balance computes grid import/export (with optional export)

    Returns:
      - next_state
      - info: diagnostics & all flows (kW) + energies (kWh) for this step
    """
    limits = limits or ElectricLimits()
    dt = th.dt_h

    # ---- Thermal update
    Tin_next, therm = _thermal_step(float(state.Tin_c), float(exog.Tout_c), float(ports.q_heat_kw), th)

    # ---- Battery update (if present)
    p_ch_proj = p_dis_proj = 0.0
    soc_next: Optional[float] = state.soc
    if bat and bat.e_kwh > 0.0 and state.soc is not None:
        p_ch_proj, p_dis_proj, soc_next, bat_info = _battery_project(
            ports.p_batt_ch_kw, ports.p_batt_dis_kw, state.soc, th, bat
        )
    else:
        bat_info = {"p_batt_ch_kw_proj": 0.0, "p_batt_dis_kw_proj": 0.0, "soc_next": state.soc}

    # ---- Electric balance (kW on AC bus)
    elec_load_kw = max(0.0, float(ports.elec_load_kw))
    base_kw = max(0.0, float(exog.base_load_kw))
    pv_used_kw = max(0.0, min(float(ports.pv_used_kw), float(exog.pv_potential_kw)))

    # Net power demand from grid: positive → import, negative → export
    net_kw = base_kw + elec_load_kw + p_ch_proj - pv_used_kw - p_dis_proj

    if limits.allow_export:
        g_import_kw = float(max(0.0, net_kw))
        g_export_kw = float(max(0.0, -net_kw))
    else:
        g_import_kw = float(max(0.0, net_kw))
        g_export_kw = 0.0

    # Grid import cap (simple clip)
    g_import_kw = float(min(g_import_kw, limits.gmax_kw))

    # Energies (kWh) this step
    g_import_kwh = g_import_kw * dt
    g_export_kwh = g_export_kw * dt
    elec_energy_kwh = elec_load_kw * dt  # device energy (excludes base load & battery)

    info: Dict[str, float] = {
        # Thermal
        "Tin_next_c": Tin_next,
        "q_heat_kw": therm["q_heat_kw"],
        "q_loss_kw": therm["q_loss_kw"],
        "dT": therm["dT"],
        # Battery (projected)
        "p_batt_ch_kw": p_ch_proj,
        "p_batt_dis_kw": p_dis_proj,
        # Electric bus
        "base_load_kw": base_kw,
        "elec_load_kw": elec_load_kw,
        "pv_used_kw": pv_used_kw,
        "net_kw": net_kw,
        "g_import_kw": g_import_kw,
        "g_export_kw": g_export_kw,
        # Energies
        "g_import_kwh": g_import_kwh,
        "g_export_kwh": g_export_kwh,
        "elec_energy_kwh": elec_energy_kwh,
    }
    info.update(bat_info)

    next_state = PlantState(Tin_c=Tin_next, soc=soc_next)
    return next_state, info


# -------------------------
# Backward-compatible helpers (old single-device flow)
# -------------------------
def step_temp(
    T_in_c: float,
    T_out_c: float,
    action_frac: float,
    params: ThermalParams,
) -> Tuple[float, Dict[str, float]]:
    """
    Legacy helper: embedded resistive heater (q = eff * Pmax * a).
    Prefer new `plant_step_multi(...)` with modular Ports/Exogenous.
    """
    a = float(np.clip(action_frac, 0.0, 1.0))
    q_heat_kw = params.heater_eff * params.heater_pmax_kw * a
    elec_power_kw = params.heater_pmax_kw * a
    T_next_c, info = _thermal_step(T_in_c, T_out_c, q_heat_kw, params)
    info.update({
        "elec_power_kw": elec_power_kw,
        "elec_energy_kwh": elec_power_kw * params.dt_h,
    })
    return T_next_c, info


def steady_state_temp(T_out_c: float, q_heat_kw: float, params: ThermalParams) -> float:
    """T* for constant Tout and thermal input q_heat_kw."""
    if params.U_kw_per_degC <= 0:
        return float(T_out_c)
    T_star = T_out_c + float(q_heat_kw) / params.U_kw_per_degC
    return float(np.clip(T_star, params.clip_temp_c[0], params.clip_temp_c[1]))


__all__ = [
    "ThermalParams",
    "BatteryParams",
    "ElectricLimits",
    "PlantState",
    "Exogenous",
    "Ports",
    "plant_step_multi",
    "step_temp",            # legacy
    "steady_state_temp",
]
