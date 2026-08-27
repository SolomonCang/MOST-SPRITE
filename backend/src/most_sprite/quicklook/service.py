from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from astropy.io import fits

from most_sprite.products.preview import downsample_image


def create_quicklook(l0_path: Path, output_path: Path, *, saturation_adu: float) -> dict:
    with fits.open(l0_path, checksum=True, memmap=False) as hdul:
        image = np.asarray(hdul[0].data, dtype=np.float64)
    preview = downsample_image(image)
    preview_rows = [
        [float(value) if np.isfinite(value) else None for value in row]
        for row in preview
    ]
    payload = {
        "shape": list(image.shape),
        "minimum": float(np.nanmin(image)),
        "maximum": float(np.nanmax(image)),
        "median": float(np.nanmedian(image)),
        "saturation_adu": saturation_adu,
        "saturated_fraction": float(np.mean(image >= saturation_adu)),
        "preview_shape": list(preview.shape),
        "preview_reducer": "finite-max-pool-v1",
        "image": preview_rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".part")
    temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temp.replace(output_path)
    return payload
