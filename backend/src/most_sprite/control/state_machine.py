from __future__ import annotations

from most_sprite.domain.enums import InstrumentState
from most_sprite.errors import SpriteError

ALLOWED_TRANSITIONS: dict[InstrumentState, set[InstrumentState]] = {
    InstrumentState.OFFLINE: {InstrumentState.INITIALIZING},
    InstrumentState.INITIALIZING: {InstrumentState.STANDBY, InstrumentState.SAFE_FAULT},
    InstrumentState.STANDBY: {
        InstrumentState.PREPARING,
        InstrumentState.CALIBRATING,
        InstrumentState.MAINTENANCE,
        InstrumentState.OFFLINE,
    },
    InstrumentState.PREPARING: {InstrumentState.READY, InstrumentState.SAFE_FAULT},
    InstrumentState.READY: {
        InstrumentState.EXPOSING,
        InstrumentState.STANDBY,
        InstrumentState.SAFE_FAULT,
    },
    InstrumentState.EXPOSING: {
        InstrumentState.READING,
        InstrumentState.STANDBY,
        InstrumentState.SAFE_FAULT,
    },
    InstrumentState.READING: {
        InstrumentState.READY,
        InstrumentState.STANDBY,
        InstrumentState.SAFE_FAULT,
    },
    InstrumentState.CALIBRATING: {InstrumentState.STANDBY, InstrumentState.SAFE_FAULT},
    InstrumentState.MAINTENANCE: {InstrumentState.STANDBY, InstrumentState.SAFE_FAULT},
    InstrumentState.SAFE_FAULT: {InstrumentState.INITIALIZING, InstrumentState.OFFLINE},
}


def assert_transition(current: InstrumentState, target: InstrumentState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise SpriteError(
            "INVALID_INSTRUMENT_TRANSITION",
            f"instrument cannot transition from {current.value} to {target.value}",
            details={"current": current.value, "target": target.value},
        )
