from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from most_sprite.calibration import match_calibration
from most_sprite.db.models import Calibration
from most_sprite.db.session import dispose_database, init_database, session_scope
from most_sprite.domain.enums import ConfigurationStatus, DataMode


@pytest.fixture
async def calibration_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "SPRITE_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'calibration.db'}"
    )
    monkeypatch.setenv("SPRITE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SPRITE_AUTO_CREATE_SCHEMA", "true")
    from most_sprite.config import get_settings

    get_settings.cache_clear()
    await dispose_database()
    await init_database()
    yield
    await dispose_database()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_match_is_explainable_and_never_uses_out_of_domain_nearest(
    calibration_database,
) -> None:
    observed = datetime.now(UTC)
    async with session_scope() as session:
        valid = Calibration(
            calibration_type="FLAT",
            mode=DataMode.POL_Q,
            uri="/cal/valid.fits",
            checksum="valid",
            status=ConfigurationStatus.APPROVED,
            valid_from=observed - timedelta(hours=1),
            valid_to=observed + timedelta(hours=1),
            parameters_json={"binning": "1x1"},
        )
        wrong_mode = Calibration(
            calibration_type="FLAT",
            mode=DataMode.NONPOL,
            uri="/cal/wrong-mode.fits",
            checksum="wrong",
            status=ConfigurationStatus.APPROVED,
            valid_from=observed - timedelta(minutes=1),
            valid_to=observed + timedelta(minutes=1),
            parameters_json={"binning": "1x1"},
        )
        expired = Calibration(
            calibration_type="FLAT",
            mode=DataMode.POL_Q,
            uri="/cal/expired.fits",
            checksum="expired",
            status=ConfigurationStatus.APPROVED,
            valid_to=observed - timedelta(seconds=1),
            parameters_json={"binning": "1x1"},
        )
        session.add_all([valid, wrong_mode, expired])
        await session.flush()
        expected_id = valid.id

    async with session_scope() as session:
        decision = await match_calibration(
            session,
            calibration_type="FLAT",
            mode=DataMode.POL_Q,
            observed_at=observed,
            required_parameters={"binning": "1x1"},
        )
        assert decision.status == "MATCHED"
        assert decision.selected_id == expected_id
        rejected_reasons = {
            reason
            for candidate in decision.candidates
            if not candidate.accepted
            for reason in candidate.reasons
        }
        assert {"MODE_MISMATCH", "VALID_TO_MISMATCH"} <= rejected_reasons


@pytest.mark.asyncio
async def test_unverified_calibration_blocks_formal_match(calibration_database) -> None:
    observed = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Calibration(
                calibration_type="THAR",
                mode=DataMode.POL_Q,
                uri="/cal/unverified.fits",
                checksum="unverified",
                status=ConfigurationStatus.UNVERIFIED,
            )
        )
    async with session_scope() as session:
        decision = await match_calibration(
            session,
            calibration_type="THAR",
            mode=DataMode.POL_Q,
            observed_at=observed,
        )
        assert decision.status == "WAITING_CALIBRATION"
        assert decision.selected_id is None
        assert decision.candidates[0].reasons == ("STATUS_MISMATCH",)
