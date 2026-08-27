from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from astropy.io import fits


def create_quicklook(l0_path: Path, output_path: Path, *, saturation_adu: float) -> dict:
    with fits.open(l0_path, checksum=True, memmap=False) as hdul:
        image = np.asarray(hdul[0].data, dtype=np.float64)
    row_step = max(1, image.shape[0] // 32)
    column_step = max(1, image.shape[1] // 32)
    preview = image[::row_step, ::column_step][:32, :32]
    payload = {
        "shape": list(image.shape),
        "minimum": float(np.nanmin(image)),
        "maximum": float(np.nanmax(image)),
        "median": float(np.nanmedian(image)),
        "saturation_adu": saturation_adu,
        "saturated_fraction": float(np.mean(image >= saturation_adu)),
        "image": preview.tolist(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".part")
    temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temp.replace(output_path)
    return payload
