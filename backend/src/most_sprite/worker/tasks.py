from __future__ import annotations

import asyncio

from most_sprite.calibration import build_calibration_run
from most_sprite.db.session import dispose_database
from most_sprite.products.processing import process_run
from most_sprite.worker.celery_app import celery_app


async def _process_run_with_isolated_engine(run_id: str, claim_token: str) -> None:
    try:
        await process_run(run_id, claim_token=claim_token)
    finally:
        # Celery invokes this synchronous task repeatedly in the same child process,
        # while asyncio.run creates a new loop for every invocation. Asyncpg
        # connections are loop-bound, so the pool must be drained before that loop
        # closes rather than reused by the next task.
        await dispose_database()


async def _build_calibration_with_isolated_engine(run_id: str) -> None:
    try:
        await build_calibration_run(run_id)
    finally:
        await dispose_database()


@celery_app.task(
    name="most_sprite.process_run",
    bind=True,
    autoretry_for=(OSError, ConnectionError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def process_run_task(self, run_id: str) -> None:  # noqa: ANN001
    asyncio.run(_process_run_with_isolated_engine(run_id, str(self.request.id)))


@celery_app.task(
    name="most_sprite.build_calibration_run",
    bind=True,
    autoretry_for=(OSError, ConnectionError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def build_calibration_run_task(self, run_id: str) -> None:  # noqa: ANN001
    del self
    asyncio.run(_build_calibration_with_isolated_engine(run_id))
