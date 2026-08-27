"""Versioned instrument adapters for immutable external observations."""

from most_sprite.pipeline.instruments.base import (
    DemodulationModel,
    DetectorProfile,
    InstrumentAdapter,
    RawDescriptor,
)
from most_sprite.pipeline.instruments.espadons import ESPaDOnSAdapter

__all__ = [
    "DemodulationModel",
    "DetectorProfile",
    "ESPaDOnSAdapter",
    "InstrumentAdapter",
    "RawDescriptor",
    "instrument_adapter",
]


def instrument_adapter(name: str) -> InstrumentAdapter:
    if name.upper() == "ESPADONS":
        return ESPaDOnSAdapter()
    raise ValueError(f"unsupported instrument adapter: {name}")
