from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass(frozen=True)
class Action:
    hvac_u: float = 0.0  # [-1, +1] cooling/heating

@dataclass
class GameState:
    k: int
    Tin_c: float
    soc: Optional[float] = None
    cum_energy_cost_eur: float = 0.0
    cum_comfort_penalty_eur: float = 0.0
    cum_reward: float = 0.0

@dataclass(frozen=True)
class Obs:
    Tin_c: float
    Tout_c: float
    price_eur_per_kwh: float
    hour_frac: float
    comfort_L_c: float
    comfort_U_c: float
    dt_h: float

@dataclass
class TickInfo:
    obs: Obs
    info: Dict[str, float]
    reward: float
    terminated: bool
    truncated: bool
    state: GameState
