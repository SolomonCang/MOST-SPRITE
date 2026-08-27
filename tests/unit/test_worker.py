from __future__ import annotations

import pytest
from most_sprite.worker import tasks


@pytest.mark.asyncio
async def test_worker_disposes_loop_bound_database_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_process(run_id: str, *, claim_token: str) -> None:
        calls.append(f"process:{run_id}:{claim_token}")

    async def fake_dispose() -> None:
        calls.append("dispose")

    monkeypatch.setattr(tasks, "process_run", fake_process)
    monkeypatch.setattr(tasks, "dispose_database", fake_dispose)

    await tasks._process_run_with_isolated_engine("run-1", "claim-1")

    assert calls == ["process:run-1:claim-1", "dispose"]


@pytest.mark.asyncio
async def test_worker_disposes_loop_bound_database_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed = False

    async def fake_process(run_id: str, *, claim_token: str) -> None:
        raise RuntimeError(f"{run_id}:{claim_token}")

    async def fake_dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(tasks, "process_run", fake_process)
    monkeypatch.setattr(tasks, "dispose_database", fake_dispose)

    with pytest.raises(RuntimeError, match="run-2"):
        await tasks._process_run_with_isolated_engine("run-2", "claim-2")

    assert disposed
