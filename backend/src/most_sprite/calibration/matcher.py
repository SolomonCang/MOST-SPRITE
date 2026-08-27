from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from most_sprite.db.models import Calibration
from most_sprite.domain.enums import ConfigurationStatus, DataMode


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    calibration_id: str
    accepted: bool
    conditions: dict[str, bool]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalibrationDecision:
    calibration_type: str
    selected_id: str | None
    status: str
    candidates: tuple[CalibrationCandidate, ...] = field(default_factory=tuple)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def match_calibration(
    session: AsyncSession,
    *,
    calibration_type: str,
    mode: DataMode,
    observed_at: datetime,
    required_parameters: dict[str, Any] | None = None,
    allow_unverified: bool = False,
) -> CalibrationDecision:
    """Return an explainable deterministic match; never choose a merely-nearest frame."""
    rows = (
        await session.scalars(
            select(Calibration)
            .where(Calibration.calibration_type == calibration_type)
            .order_by(Calibration.valid_from.desc(), Calibration.created_at.desc())
        )
    ).all()
    decisions: list[CalibrationCandidate] = []
    accepted: list[Calibration] = []
    required_parameters = required_parameters or {}
    for row in rows:
        valid_from = _aware(row.valid_from)
        valid_to = _aware(row.valid_to)
        conditions = {
            "status": row.status == ConfigurationStatus.APPROVED
            or (allow_unverified and row.status == ConfigurationStatus.UNVERIFIED),
            "mode": row.mode is None or row.mode == mode,
            "valid_from": valid_from is None or valid_from <= observed_at,
            "valid_to": valid_to is None or valid_to >= observed_at,
            "parameters": all(
                row.parameters_json.get(key) == value
                for key, value in required_parameters.items()
            ),
        }
        reasons = tuple(
            name.upper() + "_MISMATCH" for name, value in conditions.items() if not value
        )
        candidate = CalibrationCandidate(
            calibration_id=row.id,
            accepted=not reasons,
            conditions=conditions,
            reasons=reasons,
        )
        decisions.append(candidate)
        if candidate.accepted:
            accepted.append(row)
    if not accepted:
        return CalibrationDecision(
            calibration_type=calibration_type,
            selected_id=None,
            status="WAITING_CALIBRATION",
            candidates=tuple(decisions),
        )
    return CalibrationDecision(
        calibration_type=calibration_type,
        selected_id=accepted[0].id,
        status="MATCHED",
        candidates=tuple(decisions),
    )
