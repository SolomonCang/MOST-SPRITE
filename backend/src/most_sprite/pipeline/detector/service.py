from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from most_sprite.configuration import default_instrument_configuration
from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.echelle.models import CalibrationFrame


def preprocess_l0(path: Path) -> tuple[CalibrationFrame, dict[str, Any]]:
    with fits.open(path, checksum=True, memmap=False) as hdul:
        raw = np.asarray(hdul[0].data, dtype=np.float64)
        header = dict(hdul[0].header)
    detector = default_instrument_configuration()["detector"]
    gain = float(detector["gain_e_per_adu"])
    read_noise = float(detector["read_noise_e"])
    saturation = float(detector["saturation_adu"])
    bias = float(np.nanpercentile(raw, 10))
    science = (raw - bias) * gain
    variance = np.clip(science, 0, None) + read_noise**2
    dq = np.zeros(raw.shape, dtype=np.uint32)
    dq[raw >= saturation] |= DQBit.SATURATED
    dq[~np.isfinite(raw)] |= DQBit.BAD_PIXEL
    science[~np.isfinite(science)] = np.nan
    return (
        CalibrationFrame(
            data=science,
            variance=variance,
            dq=dq,
            unit="electron",
            coordinates={
                "detector_y": np.arange(raw.shape[0], dtype=np.float64),
                "detector_x": np.arange(raw.shape[1], dtype=np.float64),
            },
            config_version=str(default_instrument_configuration()["version"]),
            provenance={
                "algorithm": "detector_preprocess_v1",
                "bias_adu": bias,
                "gain_e_per_adu": gain,
                "read_noise_e": read_noise,
                "input": str(path),
            },
        ),
        header,
    )
