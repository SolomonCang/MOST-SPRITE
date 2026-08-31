"""Replay one frozen CADC dataset through the real ESPaDOnS pipeline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from sqlalchemy import select

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.testdata.fetch_cadc import (  # noqa: E402
    artifact_path,
    load_manifest,
    validate_external_cache,
    verify_artifact,
)


def _source_tree_hash() -> str:
    digest = hashlib.sha256()
    roots = (
        REPOSITORY_ROOT / "backend" / "src",
        REPOSITORY_ROOT / "configs",
        REPOSITORY_ROOT / "schemas" / "fits",
    )
    paths = sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml"}
    )
    for path in paths:
        digest.update(path.relative_to(REPOSITORY_ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _prepare_work_dir(path: Path, *, reuse: bool) -> Path:
    resolved = path.expanduser().resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ValueError("replay work data must be stored outside the source repository")
    resolved.mkdir(parents=True, exist_ok=True)
    if not reuse and any(resolved.iterdir()):
        raise ValueError("replay work directory must be empty unless --reuse is set")
    return resolved


def _numeric_array_hash(digest: Any, values: np.ndarray) -> None:
    array = np.asarray(values)
    digest.update(str(array.shape).encode())
    if np.issubdtype(array.dtype, np.floating):
        finite = np.isfinite(array)
        state = np.zeros(array.shape, dtype=np.uint8)
        state[np.isnan(array)] = 1
        state[np.isposinf(array)] = 2
        state[np.isneginf(array)] = 3
        canonical = np.where(finite, array, 0.0).astype("<f8", copy=False)
        digest.update(state.tobytes())
        digest.update(canonical.tobytes())
    elif np.issubdtype(array.dtype, np.integer):
        digest.update(array.astype("<i8", copy=False).tobytes())


def numeric_fingerprint(path: Path) -> str:
    """Hash only numerical FITS content, excluding run-specific UUID headers."""
    digest = hashlib.sha256()
    with fits.open(path, checksum=True, memmap=False) as hdul:
        for hdu in hdul:
            if hdu.data is None:
                continue
            digest.update(str(hdu.name).encode())
            values = np.asarray(hdu.data)
            if values.dtype.names:
                for name in values.dtype.names:
                    column = np.asarray(values[name])
                    if np.issubdtype(column.dtype, np.number):
                        digest.update(name.encode())
                        _numeric_array_hash(digest, column)
            elif np.issubdtype(values.dtype, np.number):
                _numeric_array_hash(digest, values)
    return digest.hexdigest()


async def _replay(manifest: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    from most_sprite.calibration import (
        approve_calibration_set,
        build_calibration_run,
        ensure_calibration_run,
    )
    from most_sprite.config import get_settings
    from most_sprite.db.models import (
        CalibrationRun,
        CalibrationSet,
        ProcessingRun,
        Product,
        Sequence,
    )
    from most_sprite.db.session import (
        dispose_database,
        init_database,
        session_scope,
    )
    from most_sprite.domain.enums import ConfigurationStatus, ProcessingStatus
    from most_sprite.imports import commit_import, inspect_import_directory
    from most_sprite.products.processing import ensure_processing_run, process_run

    get_settings.cache_clear()
    await dispose_database()
    await init_database()
    manifest_id = str(manifest["manifest_id"])
    async with session_scope() as session:
        inspection = await inspect_import_directory(
            session,
            idempotency_key=f"replay-inspect:{manifest_id}",
            root_id="cadc",
            relative_path=".",
            instrument="ESPADONS",
            created_by="cadc-regression",
        )
        if inspection.manifest_sha256 is None:
            raise RuntimeError("inspection did not produce an immutable manifest")
        batch = await commit_import(
            session,
            inspection_id=inspection.id,
            manifest_sha256=inspection.manifest_sha256,
            idempotency_key=f"replay-import:{manifest_id}",
            created_by="cadc-regression",
        )
        calibration_run = await ensure_calibration_run(
            session,
            import_batch_id=batch.id,
            idempotency_key=f"replay-calibration:{manifest_id}",
            parameter_version="espadons-olapa-v1",
            created_by="cadc-regression",
        )
        calibration_run_id = calibration_run.id
        sequence_ids = list(batch.sequence_ids_json)

    await build_calibration_run(calibration_run_id)
    async with session_scope() as session:
        calibration_run = await session.get(CalibrationRun, calibration_run_id)
        if calibration_run is None or calibration_run.status != ProcessingStatus.SUCCEEDED:
            error = calibration_run.error_message if calibration_run is not None else "missing run"
            raise RuntimeError(f"calibration replay failed: {error}")
        calibration_set = await session.scalar(
            select(CalibrationSet).where(
                CalibrationSet.calibration_run_id == calibration_run.id
            )
        )
        if calibration_set is None:
            raise RuntimeError("calibration run produced no CalibrationSet")
        if calibration_set.status != ConfigurationStatus.APPROVED:
            await approve_calibration_set(
                session,
                calibration_set_id=calibration_set.id,
                approved_by="cadc-regression-admin",
                reason="frozen public regression replay",
                accept_warnings=True,
            )
        calibration_set_id = calibration_set.id

    for sequence_id in sequence_ids:
        async with session_scope() as session:
            run = await ensure_processing_run(
                session,
                sequence_id,
                parameters={"regression_manifest": manifest_id},
                calibration_set_id=calibration_set_id,
                parameter_version="espadons-olapa-v1",
            )
            if run is None:
                raise RuntimeError(f"sequence {sequence_id} has incomplete L0 inputs")
            run_id = run.id
        await process_run(run_id)

    async with session_scope() as session:
        calibration_set = await session.get(CalibrationSet, calibration_set_id)
        assert calibration_set is not None
        sequences = list(
            (
                await session.scalars(
                    select(Sequence).where(Sequence.id.in_(sequence_ids))
                )
            ).all()
        )
        runs = list(
            (
                await session.scalars(
                    select(ProcessingRun).where(
                        ProcessingRun.sequence_id.in_(sequence_ids)
                    )
                )
            ).all()
        )
        products = list(
            (
                await session.scalars(
                    select(Product).where(Product.sequence_id.in_(sequence_ids))
                )
            ).all()
        )
        sequence_by_id = {item.id: item for item in sequences}
        if any(run.status != ProcessingStatus.SUCCEEDED for run in runs):
            failures = {run.id: run.error_message for run in runs if run.status != "SUCCEEDED"}
            raise RuntimeError(f"science replay failed: {failures}")
        summary = {
            "schema_version": 1,
            "manifest_id": manifest_id,
            "source_tree_hash": get_settings().software_commit,
            "calibration": {
                "calibration_hash": calibration_set.calibration_hash,
                "qc_flag": str(calibration_set.qc_flag),
                "trace_rms_pixel": calibration_set.qc_json.get("trace_rms_pixel"),
                "wavelength_rms_m_s": calibration_set.qc_json.get("wavelength", {}).get(
                    "wavelength_rms_m_s"
                ),
                "alignment_valid_fraction": calibration_set.qc_json.get(
                    "alignment_valid_fraction"
                ),
            },
            "processing": sorted(
                [
                    {
                        "target": sequence_by_id[run.sequence_id].target_name,
                        "mode": sequence_by_id[run.sequence_id].mode,
                        "input_hash": run.input_hash,
                        "calibration_hash": run.calibration_hash,
                        "parameter_hash": run.parameter_hash,
                        "code_hash": run.code_hash,
                    }
                    for run in runs
                ],
                key=lambda item: (item["target"], item["mode"]),
            ),
            "products": sorted(
                [
                    {
                        "target": sequence_by_id[product.sequence_id].target_name,
                        "mode": product.mode,
                        "level": product.level,
                        "variant": (
                            f"{product.metadata_json.get('normalization')}-"
                            f"{product.metadata_json.get('specsys')}"
                            if product.level == "L3"
                            else None
                        ),
                        "product_hash": product.product_hash,
                        "numeric_sha256": numeric_fingerprint(Path(product.uri)),
                        "qc_flag": product.qc_flag,
                    }
                    for product in products
                    if product.level in {"L0", "L1", "L2", "L3"}
                ],
                key=lambda item: (
                    item["target"],
                    item["mode"],
                    item["level"],
                    item["variant"] or "",
                    item["product_hash"],
                ),
            ),
        }
    await dispose_database()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a frozen public ESPaDOnS manifest from an empty database"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--expected-summary", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = load_manifest(args.manifest.resolve())
    cache = validate_external_cache(args.cache_dir)
    work_dir = _prepare_work_dir(args.work_dir, reuse=args.reuse)
    dataset_root = cache / str(manifest["manifest_id"])
    for artifact in manifest["artifacts"]:
        verify_artifact(
            artifact_path(cache, str(manifest["manifest_id"]), artifact),
            artifact,
        )
    os.environ.update(
        {
            "SPRITE_APP_ENV": "test",
            "SPRITE_AUTH_MODE": "dev",
            "SPRITE_LOCAL_AUTH_SECRET": "cadc-replay-local-auth-secret-placeholder",
            "SPRITE_DATABASE_URL": f"sqlite+aiosqlite:///{work_dir / 'sprite.db'}",
            "SPRITE_DATA_ROOT": str(work_dir / "data"),
            "SPRITE_AUTO_CREATE_SCHEMA": "true",
            "SPRITE_EMBEDDED_WORKERS": "false",
            "SPRITE_IMPORT_ROOTS": json.dumps({"cadc": str(dataset_root)}),
            "SPRITE_SOFTWARE_COMMIT": _source_tree_hash(),
        }
    )
    summary = asyncio.run(_replay(manifest, work_dir))
    destination = work_dir / "regression-summary.json"
    destination.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.expected_summary is not None:
        expected = json.loads(args.expected_summary.read_text(encoding="utf-8"))
        if summary != expected:
            raise SystemExit("replay summary differs from the expected scientific identity")
    print(destination)


if __name__ == "__main__":
    main()
