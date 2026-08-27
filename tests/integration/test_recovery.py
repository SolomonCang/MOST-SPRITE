from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from most_sprite.acquisition import recover_unregistered_l0
from most_sprite.acquisition.fits_contract import write_l0_atomic
from most_sprite.configuration import ensure_default_config
from most_sprite.db.models import (
    Command,
    ConsumedEvent,
    Exposure,
    OutboxEvent,
    ProcessingRun,
    Product,
    RawFile,
    Sequence,
    TaskRun,
)
from most_sprite.db.session import dispose_database, init_database, session_scope
from most_sprite.domain.enums import (
    DataMode,
    ExposureStatus,
    ProcessingStatus,
    SequenceStatus,
)
from most_sprite.products import processing
from most_sprite.scheduler import OutboxScheduler
from sqlalchemy import func, select


@pytest.fixture
async def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "recovery.db"
    data_root = tmp_path / "data"
    monkeypatch.setenv("SPRITE_APP_ENV", "test")
    monkeypatch.setenv("SPRITE_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("SPRITE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("SPRITE_AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("SPRITE_EMBEDDED_WORKERS", "false")
    monkeypatch.setenv("SPRITE_SIMULATION_ROWS", "64")
    monkeypatch.setenv("SPRITE_SIMULATION_COLUMNS", "64")
    from most_sprite.config import get_settings

    get_settings.cache_clear()
    await dispose_database()
    await init_database()
    async with session_scope() as session:
        await ensure_default_config(session)
    yield get_settings()
    await dispose_database()
    get_settings.cache_clear()


async def create_orphan_l0(data_root: Path) -> tuple[str, str, Path]:
    async with session_scope() as session:
        config = await ensure_default_config(session)
        sequence = Sequence(
            idempotency_key="orphan-sequence",
            target_name="RECOVERY",
            mode=DataMode.NONPOL,
            exposure_time=1.0,
            repeats=1,
            expected_exposures=1,
            completed_exposures=0,
            status=SequenceStatus.FAILED,
            config_snapshot_id=config.id,
            created_by="test",
        )
        session.add(sequence)
        await session.flush()
        exposure = Exposure(
            sequence_id=sequence.id,
            sub_index=1,
            status=ExposureStatus.READING,
            started_at=datetime.now(UTC),
        )
        session.add(exposure)
        await session.flush()
        sequence_id = sequence.id
        exposure_id = exposure.id
        config_id = config.id

    started = datetime.now(UTC)
    path = data_root / "raw" / "2026" / "08" / "26" / "recovery" / f"{exposure_id}.fits"
    write_l0_atomic(
        path,
        np.full((64, 64), 1000, dtype=np.uint16),
        raw_file_id="11111111-2222-3333-4444-555555555555",
        sequence_id=sequence_id,
        group_id=None,
        exposure_id=exposure_id,
        command_id="66666666-7777-8888-9999-000000000000",
        config_snapshot_id=config_id,
        mode=DataMode.NONPOL,
        sub_index=1,
        exposure_time=1.0,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        fr1_commanded=0.0,
        fr1_measured=0.0,
        fr3_commanded=0.0,
        fr3_measured=0.0,
        telemetry={"database_available": False},
    )
    return sequence_id, exposure_id, path


@pytest.mark.asyncio
async def test_recovery_scanner_registers_valid_file_without_false_sequence_success(
    isolated_runtime,
) -> None:
    sequence_id, exposure_id, path = await create_orphan_l0(isolated_runtime.data_root)
    async with session_scope() as session:
        assert await session.scalar(select(func.count(RawFile.id))) == 0
        assert await recover_unregistered_l0(session) == 1
    async with session_scope() as session:
        exposure = await session.get(Exposure, exposure_id)
        sequence = await session.get(Sequence, sequence_id)
        raw = await session.scalar(select(RawFile).where(RawFile.exposure_id == exposure_id))
        l0 = await session.scalar(
            select(Product).where(Product.sequence_id == sequence_id, Product.level == "L0")
        )
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.event_type == "raw_file.committed.v1")
        )
        assert exposure is not None and exposure.status == ExposureStatus.COMMITTED
        assert sequence is not None and sequence.completed_exposures == 1
        assert sequence.status == SequenceStatus.FAILED
        assert raw is not None and raw.uri == str(path.resolve())
        assert l0 is not None and l0.metadata_json["recovered"] is True
        assert event is not None and event.payload_json["recovered"] is True
        command = await session.get(Command, "66666666-7777-8888-9999-000000000000")
        assert command is not None and command.command_type == "RECOVERED_EXPOSE"


@pytest.mark.asyncio
async def test_recovery_skips_corrupt_file_and_continues_with_valid_l0(isolated_runtime) -> None:
    _, _, valid_path = await create_orphan_l0(isolated_runtime.data_root)
    invalid_path = valid_path.with_name("corrupt.fits")
    invalid_path.write_bytes(b"not-a-fits-file")
    async with session_scope() as session:
        assert await recover_unregistered_l0(session) == 1
    async with session_scope() as session:
        assert await session.scalar(select(func.count(RawFile.id))) == 1
    assert invalid_path.read_bytes() == b"not-a-fits-file"


@pytest.mark.asyncio
async def test_queue_failure_rolls_back_publish_and_duplicate_event_is_deduplicated(
    isolated_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_orphan_l0(isolated_runtime.data_root)
    async with session_scope() as session:
        await recover_unregistered_l0(session)

    from most_sprite.worker.celery_app import celery_app

    def unavailable(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise ConnectionError("simulated Redis restart")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    scheduler = OutboxScheduler(inline_processing=False)
    assert await scheduler.run_once()  # raw commit creates a durable processing-queued event
    with pytest.raises(ConnectionError, match="Redis"):
        await scheduler.run_once()
    async with session_scope() as session:
        raw_event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.event_type == "raw_file.committed.v1")
        )
        queued_event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "processing_run.state.changed.v1",
                OutboxEvent.payload_json["status"].as_string() == "QUEUED",
            )
        )
        assert raw_event is not None and raw_event.published_at is not None
        assert queued_event is not None and queued_event.published_at is None
        assert await session.scalar(select(func.count(ConsumedEvent.event_id))) == 1

    deliveries: list[tuple[str, list[str]]] = []

    def delivered(name: str, args: list[str]):
        deliveries.append((name, args))

    monkeypatch.setattr(celery_app, "send_task", delivered)
    assert await scheduler.run_once()
    assert len(deliveries) == 1
    async with session_scope() as session:
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "processing_run.state.changed.v1",
                OutboxEvent.payload_json["status"].as_string() == "QUEUED",
            )
        )
        assert event is not None
        event.published_at = None
    assert await scheduler.run_once()
    assert len(deliveries) == 1


@pytest.mark.asyncio
async def test_worker_crash_can_retry_without_duplicate_products(
    isolated_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_orphan_l0(isolated_runtime.data_root)
    async with session_scope() as session:
        await recover_unregistered_l0(session)
    scheduler = OutboxScheduler(inline_processing=False)
    from most_sprite.worker.celery_app import celery_app

    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: None)
    assert await scheduler.run_once()
    async with session_scope() as session:
        run = await session.scalar(select(ProcessingRun))
        assert run is not None
        run_id = run.id

    original_write_l2 = processing.write_l2

    def crash(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(processing, "write_l2", crash)
    with pytest.raises(RuntimeError, match="worker crash"):
        await processing.process_run(run_id)
    async with session_scope() as session:
        run = await session.get(ProcessingRun, run_id)
        task = await session.scalar(select(TaskRun).where(TaskRun.processing_run_id == run_id))
        assert run is not None and run.status == ProcessingStatus.FAILED
        assert task is not None and task.status == ProcessingStatus.FAILED

    monkeypatch.setattr(processing, "write_l2", original_write_l2)
    await processing.process_run(run_id)
    async with session_scope() as session:
        run = await session.get(ProcessingRun, run_id)
        product_count = await session.scalar(
            select(func.count(Product.id)).where(Product.sequence_id == run.sequence_id)
        )
        task_count = await session.scalar(
            select(func.count(TaskRun.id)).where(TaskRun.processing_run_id == run_id)
        )
        assert run is not None and run.status == ProcessingStatus.SUCCEEDED
        assert task_count == 1
        assert product_count == 5  # immutable L0, quicklook, L1, L2 and one L3


@pytest.mark.asyncio
async def test_fresh_claim_blocks_duplicate_worker_and_stale_claim_is_recovered(
    isolated_runtime,
) -> None:
    await create_orphan_l0(isolated_runtime.data_root)
    async with session_scope() as session:
        await recover_unregistered_l0(session)
    scheduler = OutboxScheduler(inline_processing=False)
    assert await scheduler.run_once()

    async with session_scope() as session:
        run = await session.scalar(select(ProcessingRun))
        assert run is not None
        run_id = run.id
        run.status = ProcessingStatus.RUNNING
        run.claim_token = "lost-worker"
        run.claimed_at = datetime.now(UTC)

    await processing.process_run(run_id, claim_token="duplicate-worker")
    async with session_scope() as session:
        run = await session.get(ProcessingRun, run_id)
        product_count = await session.scalar(select(func.count(Product.id)))
        assert run is not None and run.status == ProcessingStatus.RUNNING
        assert run.claim_token == "lost-worker"
        assert product_count == 2  # recovered immutable L0 plus quicklook only
        run.claimed_at = datetime.now(UTC) - timedelta(seconds=301)

    await processing.process_run(run_id, claim_token="replacement-worker")
    async with session_scope() as session:
        run = await session.get(ProcessingRun, run_id)
        product_count = await session.scalar(select(func.count(Product.id)))
        assert run is not None and run.status == ProcessingStatus.SUCCEEDED
        assert run.claim_token == "replacement-worker"
        assert product_count == 5
