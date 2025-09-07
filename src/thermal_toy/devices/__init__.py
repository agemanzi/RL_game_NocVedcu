# src/thermal_toy/devices/__init__.py
from __future__ import annotations

from typing import Dict, List, Any, Sequence

from .base import Device
from .resistive import ResistiveHeater
from .heat_pump_bidir import BiDirectionalHeatPump
from .battery import BatteryActuator
from .pv import PVInverter


REGISTRY: Dict[str, type[Device]] = {
    "resistive": ResistiveHeater,
    "bidir_hp": BiDirectionalHeatPump,
    "battery": BatteryActuator,
    "pv": PVInverter,
}


def make_device(kind: str, **kwargs) -> Device:
    key = kind.lower()
    if key not in REGISTRY:
        raise ValueError(f"Unknown device kind: {kind}. Known: {list(REGISTRY)}")
    cls = REGISTRY[key]
    return cls(**kwargs)  # type: ignore[arg-type]


def make_devices(specs: Sequence[Dict[str, Any]]) -> List[Device]:
    """
    specs = [
      {"kind":"bidir_hp", "pmax_kw":2.5, "cop_ref":3.2, ...},
      {"kind":"resistive", "pmax_kw":2.0, "eff":1.0},
      {"kind":"battery", "p_ch_max_kw":3.0, "p_dis_max_kw":3.0},
      {"kind":"pv"},
    ]
    """
    return [make_device(s["kind"], **{k:v for k,v in s.items() if k!="kind"}) for s in specs]
