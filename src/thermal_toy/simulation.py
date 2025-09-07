# src/thermal_toy/simulation.py
from __future__ import annotations

import os
import argparse
from typing import Optional, List, Dict

import numpy as np
import pandas as pd

from .io import build_scenario, load_config_yaml
from .dynamics import step_temp
from .reward import step_reward, RewardParams


def run_simulation(
    config_yaml_path: str,
    day_csv_path: str,
    *,
    action_frac: float = 0.5,
    ansi: bool = True,
) -> pd.DataFrame:
    """
    Iterate once over the CSV horizon and apply a constant heater action.
    Returns a DataFrame with per-step diagnostics.
    """
    scenario, th_params, rw_params = build_scenario(
        config_yaml_path, day_csv_path, enforce_horizon=True
    )

    a = float(np.clip(action_frac, 0.0, 1.0))
    T = scenario.T
    Tin = float(scenario.T_in0_c)

    rows: List[Dict] = []
    cum_cost = 0.0
    cum_pen = 0.0
    for k in range(T):
        Tout = float(scenario.t_out_c[k])
        price = float(scenario.price_eur_per_kwh[k])

        Tin_next, dyn = step_temp(
            T_in_c=Tin, T_out_c=Tout, action_frac=a, params=th_params
        )

        r, info_r = step_reward(
            t_in_c=Tin_next,
            t_set_c=scenario.T_set_c,
            comfort_width_c=scenario.comfort_width_c,
            price_eur_per_kwh=price,
            elec_energy_kwh=dyn["elec_energy_kwh"],
            params=rw_params if isinstance(rw_params, RewardParams) else RewardParams(),
        )

        cum_cost += info_r["cost_eur_step"]
        cum_pen += info_r["comfort_penalty_eur_step"]

        row = {
            "t": k,
            "dt_h": scenario.dt_h,
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
            "cum_energy_cost_eur": cum_cost,
            "cum_comfort_penalty_eur": cum_pen,
        }
        rows.append(row)

        if ansi:
            print(
                f"t={k:02d} Tin={Tin_next:5.2f}°C Tout={Tout:5.2f}°C "
                f"a={a:.2f} P={dyn['elec_power_kw']:.2f}kW "
                f"price={price:.3f}€/kWh "
                f"cost={info_r['cost_eur_step']:.3f}€ "
                f"pen={info_r['comfort_penalty_eur_step']:.3f}€ "
                f"J={info_r['objective_eur_step']:.3f}€"
            )

        Tin = Tin_next

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Constant-action simulation over a day CSV to test step flow."
    )
    parser.add_argument("--config", default="data/config.yaml", type=str)
    parser.add_argument("--csv", default="data/day01_prices_weather.csv", type=str)
    parser.add_argument("--action", type=float, default=0.5, help="Heater fraction in [0,1]")
    parser.add_argument("--outdir", type=str, default="outputs")
    parser.add_argument("--no-ansi", action="store_true", help="Do not print per-step HUD")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    df = run_simulation(
        config_yaml_path=args.config,
        day_csv_path=args.csv,
        action_frac=args.action,
        ansi=not args.no_ansi,
    )

    out_csv = os.path.join(args.outdir, "rollout_simulation.csv")
    df.to_csv(out_csv, index=False)

    total_cost = float(df["cost_eur_step"].sum())
    total_pen = float(df["comfort_penalty_eur_step"].sum())
    total_obj = float(df["objective_eur_step"].sum())
    print("\n--- Summary ---")
    print(f"Saved CSV: {out_csv}")
    print(
        f"Totals → energy_cost={total_cost:.2f}€, "
        f"comfort_penalty={total_pen:.2f}€, objective={total_obj:.2f}€"
    )


if __name__ == "__main__":
    main()
