# src/thermal_toy/runtime/session.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class DummySession:
    """
    Placeholder session until the real Env is wired.
    Keep method names stable so GUI code doesn’t churn later.
    """
    step_idx: int = 0
    state: Dict[str, Any] = field(default_factory=lambda: {"Tin_c": 21.0})

    def reset(self) -> Dict[str, Any]:
        self.step_idx = 0
        self.state = {"Tin_c": 21.0}
        return self.info()

    def step(self, action: Dict[str, float] | None = None) -> Dict[str, Any]:
        self.step_idx += 1
        # noop: just bounce Tin a tiny bit for fun
        self.state["Tin_c"] = 21.0 + 0.25 * ((self.step_idx % 8) - 4)
        return self.info()

    def info(self) -> Dict[str, Any]:
        return {
            "t": self.step_idx,
            "Tin_c": round(self.state["Tin_c"], 2),
            "note": "Dummy session — replace with ThermalPlantEnv later.",
        }
