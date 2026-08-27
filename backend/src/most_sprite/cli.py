from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import uvicorn

from most_sprite.acquisition import recover_unregistered_l0
from most_sprite.acquisition.fits_contract import validate_l0, write_l0_atomic
from most_sprite.config import get_settings
from most_sprite.configuration import ensure_default_config
from most_sprite.control import ControlRunner
from most_sprite.db.session import init_database, session_scope
from most_sprite.devices.grpc_server import serve_device_agent
from most_sprite.domain.enums import DataMode
from most_sprite.logging import configure_logging
from most_sprite.products.processing import ensure_quicklook_for_exposure
from most_sprite.scheduler import OutboxScheduler


def api_main() -> None:
    settings = get_settings()
    uvicorn.run(
        "most_sprite.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


async def _prepare_database() -> None:
    await init_database()
    async with session_scope() as session:
        await ensure_default_config(session)


def control_main() -> None:
    async def run() -> None:
        await _prepare_database()
        await ControlRunner().run_forever()

    configure_logging()
    asyncio.run(run())


def device_agent_main() -> None:
    configure_logging()
    asyncio.run(serve_device_agent())


def acquisition_main() -> None:
    async def run() -> None:
        await _prepare_database()
        while True:
            async with session_scope() as session:
                await recover_unregistered_l0(session)
            await asyncio.sleep(5)

    configure_logging()
    asyncio.run(run())


def quicklook_main() -> None:
    async def run() -> None:
        from sqlalchemy import select

        from most_sprite.db.models import Exposure

        await _prepare_database()
        while True:
            async with session_scope() as session:
                exposure_ids = (
                    await session.scalars(
                        select(Exposure.id).where(Exposure.raw_file_id.is_not(None))
                    )
                ).all()
                for exposure_id in exposure_ids:
                    await ensure_quicklook_for_exposure(session, exposure_id)
            await asyncio.sleep(2)

    configure_logging()
    asyncio.run(run())


def scheduler_main() -> None:
    async def run() -> None:
        await _prepare_database()
        await OutboxScheduler(inline_processing=False).run_forever()

    configure_logging()
    asyncio.run(run())


def worker_main() -> None:
    from most_sprite.worker.celery_app import celery_app

    celery_app.worker_main(
        ["worker", "--loglevel=INFO", "--queues=formal-processing", "--concurrency=1"]
    )


def smoke_l0_main() -> None:
    parser = argparse.ArgumentParser(description="Write and validate one immutable simulated L0")
    parser.add_argument("--full-frame", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    rows = settings.physical_rows if args.full_frame else settings.simulation_rows
    columns = settings.physical_columns if args.full_frame else settings.simulation_columns
    exposure_id = str(uuid4())
    now = datetime.now(UTC)
    rng = np.random.default_rng(42)
    image = rng.integers(790, 810, size=(rows, columns), dtype=np.uint16)
    path = settings.data_root / "smoke" / f"{exposure_id}.fits"
    write_l0_atomic(
        path,
        image,
        raw_file_id=str(uuid4()),
        sequence_id=str(uuid4()),
        group_id=str(uuid4()),
        exposure_id=exposure_id,
        command_id=str(uuid4()),
        config_snapshot_id=str(uuid4()),
        mode=DataMode.POL_Q,
        sub_index=1,
        exposure_time=1.0,
        started_at=now,
        ended_at=now + timedelta(seconds=1),
        fr1_commanded=0.0,
        fr1_measured=0.0,
        fr3_commanded=0.0,
        fr3_measured=0.0,
        telemetry={"smoke_test": True, "full_frame": args.full_frame},
    )
    validate_l0(path)
    print(path.resolve())
