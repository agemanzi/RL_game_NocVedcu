from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional

# ------------------------------
# Legacy dummy session (kept)
# ------------------------------
@dataclass
class DummySession:
    step_idx: int = 0
    state: Dict[str, Any] = field(default_factory=lambda: {"Tin_c": 21.0})

    def reset(self) -> Dict[str, Any]:
        self.step_idx = 0
        self.state = {"Tin_c": 21.0}
        return self.info()

    def step(self, action: Dict[str, float] | None = None) -> Dict[str, Any]:
        self.step_idx += 1
        self.state["Tin_c"] = 21.0 + 0.25 * ((self.step_idx % 8) - 4)
        return self.info()

    def info(self) -> Dict[str, Any]:
        return {
            "t": self.step_idx,
            "Tin_c": round(self.state["Tin_c"], 2),
            "note": "Dummy session — replace with GameSession (engine) when ready.",
        }

# ------------------------------
# Engine-backed session (new)
# ------------------------------
class GameSession:
    """
    Thin adapter so GUI can call .reset/.step with a dict, like DummySession did,
    but backed by the real Engine (indoor thermal balance + HVAC sizing).
    """
    def __init__(
        self,
        config_yaml_path: str = "data/config.yaml",
        day_csv_path: str = "data/day01_prices_weather.csv",
        *,
        overrides: Optional[dict] = None,
        debug: bool = False,
    ):
        self._engine = None
        self._fallback = DummySession()
        self._init_error: Optional[str] = None

        try:
            from ..engine.engine import Engine  # type: ignore
            self._engine = Engine(
                config_yaml_path=config_yaml_path,
                day_csv_path=day_csv_path,
                overrides=overrides or {},
                debug=bool(debug),
            )
        except Exception as e:  # pragma: no cover
            self._engine = None
            self._init_error = f"{e.__class__.__name__}: {e}"

    def reset(self) -> Dict[str, Any]:
        if self._engine is None:
            info = self._fallback.reset()
            if self._init_error:
                info["engine_init_error"] = self._init_error
            return info
        tick = self._engine.reset()
        return self._flatten(tick)

    def step(self, action: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if self._engine is None:
            return self._fallback.step(action)
        from ..engine.types import Action  # local import keeps this module lightweight
        u = float(action.get("u", 0.0)) if action else 0.0
        tick = self._engine.step(Action(hvac_u=u))
        return self._flatten(tick)

    @staticmethod
    def _flatten(tick) -> Dict[str, Any]:
        d = dict(tick.info)
        d.update({
            "reward": float(tick.reward),
            "hour": float(tick.obs.hour_frac),
            "terminated": bool(tick.terminated),
            "truncated": bool(tick.truncated),
        })
        return d

__all__ = ["DummySession", "GameSession"]
