# src/thermal_toy/io.py
from __future__ import annotations

import os
import math
import random
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd

try:
    import yaml  # type: ignore
except Exception as e:  # pragma: no cover
    yaml = None

from .dynamics import ThermalParams
from .reward import RewardParams


# -------------------------
# Reproducible seeding
# -------------------------
def set_global_seed(seed: Optional[int]) -> None:
    """Seed python, numpy for reproducibility (torch/others can be seeded elsewhere)."""
    if seed is None:
        return
    try:
        import torch  # optional
        torch.manual_seed(seed)  # type: ignore[attr-defined]
    except Exception:
        pass
    random.seed(seed)
    np.random.seed(seed)


# -------------------------
# Lightweight data classes
# -------------------------
@dataclass(frozen=True)
class Scenario:
    """One-day scenario with weather & price time series, plus comfort config."""
    t: np.ndarray                 # shape (T,), integer time index
    dt_h: float                   # step in hours (assumed constant)
    t_out_c: np.ndarray           # shape (T,)
    price_eur_per_kwh: np.ndarray # shape (T,)
    T_in0_c: float
    T_set_c: float
    comfort_width_c: float

    @property
    def T(self) -> int:
        return int(self.t.shape[0])


# -------------------------
# Config & CSV loading
# -------------------------
def load_config_yaml(path: str) -> Dict:
    """Load YAML config into a plain dict."""
    if yaml is None:
        raise ImportError(
            "PyYAML is required to read YAML config. Install with `pip install pyyaml`."
        )
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError("Config YAML must map to a dict at the top level.")
    return cfg


def _coerce_float(x, name: str) -> float:
    try:
        return float(x)
    except Exception as e:
        raise ValueError(f"Expected a float for `{name}`, got {x!r}") from e


def _coerce_int(x, name: str) -> int:
    try:
        return int(x)
    except Exception as e:
        raise ValueError(f"Expected an int for `{name}`, got {x!r}") from e


def build_params_from_config(cfg: Dict) -> Tuple[ThermalParams, RewardParams, Dict[str, float]]:
    """
    Construct ThermalParams & RewardParams from config dict.
    Returns (thermal_params, reward_params, comfort_dict).
    """
    dt_h = _coerce_float(cfg.get("dt_h", 0.25), "dt_h")
    thermal = ThermalParams(
        dt_h=dt_h,
        C_th_kwh_per_degC=_coerce_float(cfg.get("C_th_kwh_per_degC", 2.0), "C_th_kwh_per_degC"),
        U_kw_per_degC=_coerce_float(cfg.get("U_kw_per_degC", 0.30), "U_kw_per_degC"),
        heater_pmax_kw=_coerce_float(cfg.get("heater_pmax_kw", 3.0), "heater_pmax_kw"),
        heater_eff=_coerce_float(cfg.get("heater_eff", 1.0), "heater_eff"),
        clip_temp_c=tuple(cfg.get("clip_temp_c", [-10.0, 40.0])),  # type: ignore[arg-type]
    )
    reward = RewardParams(
        lambda_temp_eur_per_degCh=_coerce_float(
            cfg.get("lambda_temp_eur_per_degCh", 2.0), "lambda_temp_eur_per_degCh"
        ),
        dt_h=dt_h,
        price_norm_ref_eur_per_kwh=_coerce_float(
            cfg.get("price_norm_ref_eur_per_kwh", 0.5), "price_norm_ref_eur_per_kwh"
        ),
    )
    comfort = {
        "T_in0_c": _coerce_float(cfg.get("T_in0_c", 19.0), "T_in0_c"),
        "T_set_c": _coerce_float(cfg.get("T_set_c", 21.0), "T_set_c"),
        "comfort_width_c": _coerce_float(cfg.get("comfort_width_c", 2.0), "comfort_width_c"),
    }
    return thermal, reward, comfort


def load_day_csv(path: str) -> pd.DataFrame:
    """
    Load a day CSV with columns:
      - t (int, 0..T-1)
      - dt_h (float)
      - t_out_c (float, °C)
      - price_eur_per_kwh (float, €/kWh)
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found: {path}")
    df = pd.read_csv(path)
    required = ["t", "dt_h", "t_out_c", "price_eur_per_kwh"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV {path} missing columns: {missing}")

    # Basic type coercion & sorting by t
    df = df.sort_values("t").reset_index(drop=True)
    df["t"] = df["t"].astype(int)
    for col in ["dt_h", "t_out_c", "price_eur_per_kwh"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    if df["t"].iloc[0] != 0:
        raise ValueError("Time index must start at t=0.")
    if not np.all(np.diff(df["t"].values) == 1):
        raise ValueError("Time index t must be consecutive integers (0..T-1).")
    if df["dt_h"].nunique() != 1:
        raise ValueError("dt_h must be constant across the file.")

    return df


def build_scenario(
    config_yaml_path: str,
    day_csv_path: str,
    *,
    enforce_horizon: bool = True,
) -> Tuple[Scenario, ThermalParams, RewardParams]:
    """
    Load config + CSV and create a ready-to-use Scenario along with params.

    If enforce_horizon is True and `horizon_steps` is present in config,
    the CSV will be cropped to that length (or raise if shorter).
    """
    cfg = load_config_yaml(config_yaml_path)
    thermal, reward, comfort = build_params_from_config(cfg)
    df = load_day_csv(day_csv_path)

    # Enforce/derive horizon
    T_csv = int(df.shape[0])
    if enforce_horizon and "horizon_steps" in cfg:
        T_cfg = _coerce_int(cfg["horizon_steps"], "horizon_steps")
        if T_csv < T_cfg:
            raise ValueError(
                f"CSV has only {T_csv} rows but horizon_steps={T_cfg}. Add more rows."
            )
        if T_csv > T_cfg:
            df = df.iloc[:T_cfg].copy()
            T_csv = T_cfg

    scenario = Scenario(
        t=df["t"].to_numpy(dtype=np.int32),
        dt_h=float(df["dt_h"].iloc[0]),
        t_out_c=df["t_out_c"].to_numpy(dtype=np.float32),
        price_eur_per_kwh=df["price_eur_per_kwh"].to_numpy(dtype=np.float32),
        T_in0_c=float(comfort["T_in0_c"]),
        T_set_c=float(comfort["T_set_c"]),
        comfort_width_c=float(comfort["comfort_width_c"]),
    )
    # Sanity: dt_h in CSV should match config dt_h (within small tolerance)
    if not math.isclose(scenario.dt_h, thermal.dt_h, rel_tol=0, abs_tol=1e-9):
        raise ValueError(
            f"dt_h mismatch: CSV dt_h={scenario.dt_h} vs config dt_h={thermal.dt_h}."
        )

    return scenario, thermal, reward


# -------------------------
# Utility exporters
# -------------------------
def scenario_to_dataframe(
    scenario: Scenario,
) -> pd.DataFrame:
    """Pack a Scenario back into a DataFrame (useful for logging/plots)."""
    return pd.DataFrame(
        {
            "t": scenario.t,
            "dt_h": scenario.dt_h,
            "t_out_c": scenario.t_out_c,
            "price_eur_per_kwh": scenario.price_eur_per_kwh,
            "T_in0_c": scenario.T_in0_c,
            "T_set_c": scenario.T_set_c,
            "comfort_width_c": scenario.comfort_width_c,
        }
    )


__all__ = [
    "Scenario",
    "set_global_seed",
    "load_config_yaml",
    "build_params_from_config",
    "load_day_csv",
    "build_scenario",
    "scenario_to_dataframe",
]
