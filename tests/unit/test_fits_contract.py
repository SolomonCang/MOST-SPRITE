from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from astropy.io import fits
from most_sprite.acquisition.fits_contract import validate_l0, write_l0_atomic
from most_sprite.domain.enums import DataMode


def test_l0_is_checked_and_atomically_committed(tmp_path: Path) -> None:
    final = tmp_path / "raw" / "exposure.fits"
    now = datetime.now(UTC)
    checksum, datasum = write_l0_atomic(
        final,
        np.arange(64 * 64, dtype=np.uint16).reshape(64, 64),
        raw_file_id="11111111-1111-1111-1111-111111111111",
        sequence_id="22222222-2222-2222-2222-222222222222",
        group_id="33333333-3333-3333-3333-333333333333",
        exposure_id="44444444-4444-4444-4444-444444444444",
        command_id="55555555-5555-5555-5555-555555555555",
        config_snapshot_id="66666666-6666-6666-6666-666666666666",
        mode=DataMode.POL_Q,
        sub_index=1,
        exposure_time=10.0,
        started_at=now,
        ended_at=now + timedelta(seconds=10),
        fr1_commanded=0.0,
        fr1_measured=0.001,
        fr3_commanded=0.0,
        fr3_measured=-0.001,
        telemetry={"guider_locked": True},
    )

    assert final.exists()
    assert not final.with_suffix(".fits.part").exists()
    validate_l0(final)
    with fits.open(final, checksum=True, memmap=False) as hdul:
        assert hdul[0].data.shape == (64, 64)
        assert hdul[0].header["SCHEMVER"] == "L0-v1"
        assert {hdu.name for hdu in hdul} >= {"TELEMETRY", "PROVENANCE"}
        assert checksum == hdul[0].header["CHECKSUM"]
        assert datasum == hdul[0].header["DATASUM"]
