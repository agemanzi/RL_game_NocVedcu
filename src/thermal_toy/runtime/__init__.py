from __future__ import annotations

"""
Re-export session types so callers can do:

    from thermal_toy.runtime import DummySession, GameSession
"""

try:
    from .session import DummySession, GameSession  # type: ignore F401
except Exception:
    # Fallback stubs if session import fails at import-time for any reason.
    class DummySession:  # type: ignore
        def __init__(self, *_, **__): pass
        def reset(self): return {"t": 0, "Tin_c": 21.0}
        def step(self, action=None): return {"t": 1, "Tin_c": 21.0}

    class GameSession(DummySession):  # type: ignore
        pass

__all__ = ["DummySession", "GameSession"]
