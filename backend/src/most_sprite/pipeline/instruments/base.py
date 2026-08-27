from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from most_sprite.domain.enums import DataMode
from most_sprite.pipeline.echelle.models import CalibrationFrame


@dataclass(frozen=True, slots=True)
class DetectorProfile:
    instrument: str
    detector: str
    version: str
    gain_e_per_adu: tuple[float, ...]
    read_noise_e: tuple[float, ...]
    saturation_adu: float
    raw_shape: tuple[int, int]
    canonical_shape: tuple[int, int]
    data_section: str
    overscan_sections: tuple[str, ...]
    axis_transform: str


@dataclass(frozen=True, slots=True)
class DemodulationModel:
    version: str
    science_signs: tuple[int, int, int, int]
    null1_signs: tuple[int, int, int, int]
    null2_signs: tuple[int, int, int, int]
    output_sign: float
    beam_roles: tuple[str, str] = ("O_BEAM", "E_BEAM")


@dataclass(frozen=True, slots=True)
class RawDescriptor:
    path: Path
    relative_path: str
    size: int
    sha256: str
    role: str
    instrument: str
    detector: str
    source_format: str
    image_hdu: int | None
    mode: DataMode | None
    stokes: str | None
    sub_index: int | None
    sequence_number: int | None
    target_name: str
    exposure_time: float
    observing_night: str
    observed_at: str | None
    readout_mode: str
    header: dict[str, Any] = field(default_factory=dict)

    def manifest_record(self) -> dict[str, Any]:
        record = asdict(self)
        record.pop("path")
        record["mode"] = self.mode.value if self.mode is not None else None
        return record


class InstrumentAdapter(Protocol):
    name: str
    version: str

    def inspect(self, path: Path, *, relative_path: str) -> RawDescriptor: ...

    def group_science(self, descriptors: list[RawDescriptor]) -> list[dict[str, Any]]: ...

    def detector_profile(self, descriptor: RawDescriptor) -> DetectorProfile: ...

    def canonical_image(
        self, path: Path
    ) -> tuple[NDArray[np.uint16], dict[str, Any], DetectorProfile]: ...

    def preprocess(
        self,
        path: Path,
        *,
        master_bias: NDArray[np.float64] | None = None,
        flat_response: NDArray[np.float64] | None = None,
    ) -> tuple[CalibrationFrame, dict[str, Any], DetectorProfile]: ...

    def demodulation_model(self, mode: DataMode) -> DemodulationModel: ...
