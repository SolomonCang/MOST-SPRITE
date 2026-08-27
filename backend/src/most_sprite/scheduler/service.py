from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from most_sprite.calibration import build_calibration_run
from most_sprite.config import get_settings
from most_sprite.db.models import CalibrationRun, ConsumedEvent, OutboxEvent, ProcessingRun
from most_sprite.db.session import session_scope
from most_sprite.domain.enums import EventType, ProcessingStatus
from most_sprite.products.processing import (
    ensure_processing_run,
    ensure_quicklook_for_exposure,
    process_run,
)


class OutboxScheduler:
    def __init__(self, *, inline_processing: bool | None = None) -> None:
        self.inline_processing = (
            get_settings().embedded_workers if inline_processing is None else inline_processing
        )
        self._stopping = False

    async def run_forever(self, poll_seconds: float = 0.25) -> None:
        while not self._stopping:
            handled = await self.run_once()
            if not handled:
                await asyncio.sleep(poll_seconds)

    def stop(self) -> None:
        self._stopping = True

    async def run_once(self) -> bool:
        run_id: str | None = None
        calibration_run_id: str | None = None
        async with session_scope() as session:
            event = await session.scalar(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.sequence_no)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if event is None:
                return False
            consumed = await session.get(
                ConsumedEvent, {"event_id": event.event_id, "consumer": "scheduler"}
            )
            if consumed is None:
                if event.event_type == EventType.RAW_FILE_COMMITTED:
                    if event.exposure_id:
                        await ensure_quicklook_for_exposure(session, event.exposure_id)
                    if event.sequence_id:
                        await ensure_processing_run(session, event.sequence_id)
                elif (
                    event.event_type == EventType.PROCESSING_RUN_STATE_CHANGED
                    and event.payload_json.get("status") == ProcessingStatus.QUEUED
                ):
                    candidate = await session.get(
                        ProcessingRun, event.payload_json.get("processing_run_id")
                    )
                    if candidate is not None and candidate.status != ProcessingStatus.SUCCEEDED:
                        run_id = candidate.id
                elif (
                    event.event_type == EventType.CALIBRATION_RUN_STATE_CHANGED
                    and event.payload_json.get("status") == ProcessingStatus.QUEUED
                ):
                    calibration_candidate = await session.get(
                        CalibrationRun, event.payload_json.get("calibration_run_id")
                    )
                    if (
                        calibration_candidate is not None
                        and calibration_candidate.status != ProcessingStatus.SUCCEEDED
                    ):
                        calibration_run_id = calibration_candidate.id
                session.add(ConsumedEvent(event_id=event.event_id, consumer="scheduler"))
            if run_id and not self.inline_processing:
                from most_sprite.worker.celery_app import celery_app

                celery_app.send_task("most_sprite.process_run", args=[run_id])
            if calibration_run_id and not self.inline_processing:
                from most_sprite.worker.celery_app import celery_app

                celery_app.send_task(
                    "most_sprite.build_calibration_run", args=[calibration_run_id]
                )
            event.published_at = datetime.now(UTC)
        if run_id and self.inline_processing:
            await process_run(run_id, claim_token=f"inline:{run_id}")
        if calibration_run_id and self.inline_processing:
            await build_calibration_run(calibration_run_id)
        return True
