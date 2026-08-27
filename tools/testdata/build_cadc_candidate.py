"""Build test-only numerical comparison bundles from real replay products."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from scipy.ndimage import median_filter

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.adapters.espadons import (  # noqa: E402
    GROUPS,
    STANDARD_GROUPS,
    ESPaDOnSGroup,
    match_spectral_line_continuum,
    merge_polarization_reference,
    read_intensity_reference,
    read_polarization_reference,
    robust_continuum_rms,
    split_intensity_reference_orders,
    wavelength_resolution_offsets,
)
from tools.testdata.fetch_cadc import (  # noqa: E402
    artifact_path,
    load_manifest,
    validate_external_cache,
    verify_artifact,
)

L3_DATASETS: tuple[tuple[str, ESPaDOnSGroup, str], ...] = (
    ("Q", GROUPS["Q"], "ad_replay"),
    ("U", GROUPS["U"], "ad_replay"),
    ("V", GROUPS["V"], "ad_replay"),
    ("HR_5501_V", STANDARD_GROUPS["HR_5501_V"], "hr_replay"),
    ("HD_236928_Q", STANDARD_GROUPS["HD_236928_Q"], "hd_replay"),
    ("HD_236928_U", STANDARD_GROUPS["HD_236928_U"], "hd_replay"),
)

_LIGHT_SPEED_KM_S = 299_792.458
# The AD Leo reference reports per-pixel S/N below 30 in m=55 and bluer.
# L2 continuum/wavelength release metrics therefore use m=24..54; all orders
# remain present in the candidate product and are tested structurally elsewhere.
_L2_ORDER_RANGE = range(24, 55)


def _manifest_for_label(label: str) -> Path:
    if label in GROUPS:
        stem = "ad-leo"
    else:
        stem = "hr-5501" if label.startswith("HR_") else "hd-236928"
    return REPOSITORY_ROOT / "tests" / "data-manifests" / f"cadc-espadons-{stem}-v1.yaml"


def _outside_repository(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ValueError("candidate bundles must be stored outside the repository")
    return resolved


def _find_l3(replay_root: Path, group: ESPaDOnSGroup) -> Path:
    matches = list(
        replay_root.glob(f"data/products/**/L3/*-POL_{group.stokes}-NORMALIZED-HELIOCEN.fits")
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected one normalized HELIOCEN POL_{group.stokes} product "
            f"under {replay_root}, found {len(matches)}"
        )
    return matches[0]


def _find_l2(replay_root: Path, raw_product_id: str) -> Path:
    database = replay_root / "sprite.db"
    if not database.is_file():
        raise ValueError(f"replay database does not exist: {database}")
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT exposures.id
            FROM exposures
            JOIN raw_files ON raw_files.id = exposures.raw_file_id
            WHERE raw_files.uri LIKE ?
            """,
            (f"%/{raw_product_id}.fits.fz",),
        ).fetchall()
    if len(rows) != 1:
        raise ValueError(
            f"expected one replay exposure for {raw_product_id}, found {len(rows)}"
        )
    matches = list(replay_root.glob(f"data/products/**/L2/{rows[0][0]}.fits"))
    if len(matches) != 1:
        raise ValueError(
            f"expected one L2 product for {raw_product_id}, found {len(matches)}"
        )
    return matches[0]


def _reference_path(
    cache: Path,
    manifest: dict[str, Any],
    product_id: str,
) -> Path:
    artifact = next(item for item in manifest["artifacts"] if item["product_id"] == product_id)
    path = artifact_path(cache, str(manifest["manifest_id"]), artifact)
    verify_artifact(path, artifact)
    return path


def _high_pass_signal(values: np.ndarray, *, continuum_size: int) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(array)
    fill = float(np.nanmedian(array[finite])) if finite.any() else 1.0
    filled = np.where(finite, array, fill)
    continuum = median_filter(filled, continuum_size, mode="nearest")
    normalized = np.divide(
        filled,
        continuum,
        out=np.ones(filled.shape, dtype=np.float64),
        where=np.isfinite(continuum) & (continuum != 0),
    )
    return normalized - median_filter(normalized, 101, mode="nearest")


def _velocity_score(
    velocity_km_s: float,
    *,
    candidate_wave: np.ndarray,
    candidate_signal: np.ndarray,
    candidate_valid: np.ndarray,
    reference_wave: np.ndarray,
    reference_signal: np.ndarray,
) -> float:
    comparison_wave = candidate_wave * (1.0 + velocity_km_s / _LIGHT_SPEED_KM_S)
    interpolated = np.interp(
        comparison_wave,
        reference_wave,
        reference_signal,
        left=np.nan,
        right=np.nan,
    )
    valid = candidate_valid & np.isfinite(interpolated)
    if np.count_nonzero(valid) < 100:
        return float("-inf")
    candidate = candidate_signal[valid] - np.mean(candidate_signal[valid])
    reference = interpolated[valid] - np.mean(interpolated[valid])
    denominator = float(np.linalg.norm(candidate) * np.linalg.norm(reference))
    return float(np.dot(candidate, reference) / denominator) if denominator > 0 else -np.inf


def _match_velocity(
    *,
    candidate_wave: np.ndarray,
    candidate_flux: np.ndarray,
    candidate_valid: np.ndarray,
    reference_wave: np.ndarray,
    reference_flux: np.ndarray,
) -> tuple[float, float]:
    candidate_signal = _high_pass_signal(candidate_flux, continuum_size=401)
    reference_signal = _high_pass_signal(reference_flux, continuum_size=301)

    def scores(velocities: np.ndarray) -> np.ndarray:
        return np.asarray(
            [
                _velocity_score(
                    float(velocity),
                    candidate_wave=candidate_wave,
                    candidate_signal=candidate_signal,
                    candidate_valid=candidate_valid,
                    reference_wave=reference_wave,
                    reference_signal=reference_signal,
                )
                for velocity in velocities
            ],
            dtype=np.float64,
        )

    coarse = np.arange(-2.0, 2.0001, 0.1)
    coarse_scores = scores(coarse)
    coarse_best = float(coarse[int(np.argmax(coarse_scores))])
    fine = np.arange(
        max(-2.0, coarse_best - 0.1),
        min(2.0, coarse_best + 0.1) + 0.0001,
        0.01,
    )
    fine_scores = scores(fine)
    index = int(np.argmax(fine_scores))
    velocity = float(fine[index])
    score = float(fine_scores[index])
    separated = np.abs(coarse - velocity) >= 1.0
    contrast = score - float(np.max(coarse_scores[separated]))
    if (
        not np.isfinite(score)
        or score < 0.1
        or contrast < 0.002
        or abs(velocity) >= 1.99
    ):
        raise ValueError(
            "L2 reference line match is not unique enough: "
            f"velocity={velocity:.3f} km/s, correlation={score:.3f}, "
            f"contrast={contrast:.3f}"
        )
    return velocity, score


def _build_l2_bundle(
    *,
    raw_product_id: str,
    intensity_product_id: str,
    replay_root: Path,
    cache: Path,
    manifest: dict[str, Any],
    destination: Path,
) -> dict[str, Any]:
    reference = read_intensity_reference(
        _reference_path(cache, manifest, intensity_product_id),
        normalized=True,
        velocity_corrected=False,
    )
    references = split_intensity_reference_orders(reference)
    heliocentric_velocity = float(
        reference.provenance["heliocentric_velocity_km_s"]
    )
    heliocentric_factor = 1.0 + heliocentric_velocity / _LIGHT_SPEED_KM_S
    candidate_path = _find_l2(replay_root, raw_product_id)

    candidate_wave_parts: list[np.ndarray] = []
    reference_wave_parts: list[np.ndarray] = []
    candidate_flux_parts: list[np.ndarray] = []
    reference_flux_parts: list[np.ndarray] = []
    mask_parts: list[np.ndarray] = []
    order_parts: list[np.ndarray] = []
    metrics: dict[str, dict[str, float | int]] = {}
    with fits.open(candidate_path, checksum=True, memmap=False) as hdul:
        tables = {role: hdul[role].data for role in ("O_BEAM", "E_BEAM")}
        for order in _L2_ORDER_RANGE:
            extracted: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
            for role in ("O_BEAM", "E_BEAM"):
                table = tables[role]
                selected = table["ORDER"] == order
                extracted.append(
                    (
                        np.asarray(table["WAVE"][selected], dtype=np.float64),
                        np.asarray(table["FLUX"][selected], dtype=np.float64),
                        np.asarray(table["DQ"][selected], dtype=np.uint32),
                    )
                )
            candidate_wave = (extracted[0][0] + extracted[1][0]) / 2.0
            candidate_flux = extracted[0][1] + extracted[1][1]
            candidate_dq = extracted[0][2] | extracted[1][2]
            pixel = np.arange(candidate_wave.size)
            candidate_valid = (
                (candidate_dq == 0)
                & np.isfinite(candidate_wave)
                & np.isfinite(candidate_flux)
                & (candidate_flux > 0)
                & (pixel > 300)
                & (pixel < 4300)
            )

            order_reference = references[order]
            reference_wave = order_reference.wavelength_nm / heliocentric_factor
            try:
                velocity, correlation = _match_velocity(
                    candidate_wave=candidate_wave,
                    candidate_flux=candidate_flux,
                    candidate_valid=candidate_valid,
                    reference_wave=reference_wave,
                    reference_flux=order_reference.intensity,
                )
            except ValueError as exc:
                raise ValueError(
                    f"{raw_product_id} physical order {order}: {exc}"
                ) from exc
            paired_reference_wave = candidate_wave * (
                1.0 + velocity / _LIGHT_SPEED_KM_S
            )
            interpolated_reference = np.interp(
                paired_reference_wave,
                reference_wave,
                order_reference.intensity,
                left=np.nan,
                right=np.nan,
            )
            ratio = np.divide(
                candidate_flux,
                interpolated_reference,
                out=np.full(candidate_flux.shape, np.nan, dtype=np.float64),
                where=np.isfinite(interpolated_reference)
                & (interpolated_reference != 0),
            )
            ratio_valid = candidate_valid & np.isfinite(ratio) & (ratio > 0)
            fill = float(np.nanmedian(ratio[ratio_valid]))
            smooth_ratio = median_filter(
                np.where(ratio_valid, ratio, fill), 401, mode="nearest"
            )
            matched_candidate_flux = np.divide(
                candidate_flux,
                smooth_ratio,
                out=np.full(candidate_flux.shape, np.nan, dtype=np.float64),
                where=np.isfinite(smooth_ratio) & (smooth_ratio > 0),
            )
            continuum_mask = (
                ratio_valid
                & np.isfinite(matched_candidate_flux)
                & (interpolated_reference >= 0.97)
                & (interpolated_reference <= 1.03)
            )
            selected_pixels = (pixel > 300) & (pixel < 4300)
            candidate_wave_parts.append(candidate_wave[selected_pixels])
            reference_wave_parts.append(paired_reference_wave[selected_pixels])
            candidate_flux_parts.append(matched_candidate_flux[selected_pixels])
            reference_flux_parts.append(interpolated_reference[selected_pixels])
            mask_parts.append(continuum_mask[selected_pixels])
            order_parts.append(
                np.full(np.count_nonzero(selected_pixels), order, dtype=np.int16)
            )
            metrics[str(order)] = {
                "velocity_offset_km_s": velocity,
                "line_correlation": correlation,
                "continuum_samples": int(np.count_nonzero(continuum_mask)),
            }

    candidate_wavelength = np.concatenate(candidate_wave_parts)
    reference_wavelength = np.concatenate(reference_wave_parts)
    candidate_intensity = np.concatenate(candidate_flux_parts)
    reference_intensity = np.concatenate(reference_flux_parts)
    continuum_mask = np.concatenate(mask_parts)
    orders = np.concatenate(order_parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        candidate_wavelength_nm=candidate_wavelength,
        reference_wavelength_nm=reference_wavelength,
        candidate_flux=candidate_intensity,
        reference_flux=reference_intensity,
        continuum_mask=continuum_mask,
        order=orders,
    )
    median_resolution_offset = float(
        np.median(
            wavelength_resolution_offsets(
                candidate_wavelength, reference_wavelength
            )[continuum_mask]
        )
    )
    continuum_rms = robust_continuum_rms(
        candidate_intensity, reference_intensity, continuum_mask
    )
    return {
        "raw_product_id": raw_product_id,
        "candidate_product": str(candidate_path),
        "reference_product_id": intensity_product_id,
        "heliocentric_velocity_km_s": heliocentric_velocity,
        "valid_continuum_samples": int(np.count_nonzero(continuum_mask)),
        "median_wavelength_offset_resolution_units": median_resolution_offset,
        "robust_continuum_rms": continuum_rms,
        "order_metrics": metrics,
        "comparison_only": True,
    }


def _build_l3_bundle(
    *,
    label: str,
    group: ESPaDOnSGroup,
    replay_root: Path,
    cache: Path,
    destination: Path,
) -> dict[str, Any]:
    manifest = load_manifest(_manifest_for_label(label))
    reference = read_polarization_reference(
        _reference_path(cache, manifest, group.polarization_product_id)
    )
    candidate_path = _find_l3(replay_root, group)
    with fits.open(candidate_path, checksum=True, memmap=False) as hdul:
        table = hdul["SPECTRUM"].data
        wavelength = np.asarray(table["WAVE"], dtype=np.float64)
        raw_polarization = np.asarray(table["P"], dtype=np.float64)
        raw_null1 = np.asarray(table["N1"], dtype=np.float64)
        raw_null2 = np.asarray(table["N2"], dtype=np.float64)
        candidate_uncertainty_polarization = np.asarray(
            table["ERR_P"], dtype=np.float64
        )
        candidate_uncertainty_null1 = np.asarray(table["ERR_N1"], dtype=np.float64)
        candidate_uncertainty_null2 = np.asarray(table["ERR_N2"], dtype=np.float64)
        dq = np.asarray(table["DQ"], dtype=np.uint32)
    merged = merge_polarization_reference(reference, wavelength)
    mask = (
        (dq == 0)
        & np.isfinite(raw_polarization)
        & np.isfinite(merged.polarization)
        & np.isfinite(merged.uncertainty)
        & (merged.uncertainty > 0)
    )
    candidate_polarization = match_spectral_line_continuum(
        wavelength,
        raw_polarization,
        merged.polarization,
        mask,
    )
    candidate_null1 = match_spectral_line_continuum(
        wavelength,
        raw_null1,
        merged.null1,
        mask,
    )
    candidate_null2 = match_spectral_line_continuum(
        wavelength,
        raw_null2,
        merged.null2,
        mask,
    )
    r_band = mask & (wavelength >= 550.0) & (wavelength <= 700.0)
    if not np.any(r_band):
        raise ValueError(f"{label} has no valid R-band candidate samples")
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        wavelength_nm=wavelength,
        candidate_polarization=candidate_polarization,
        candidate_null1=candidate_null1,
        candidate_null2=candidate_null2,
        raw_candidate_polarization=raw_polarization,
        candidate_uncertainty_polarization=candidate_uncertainty_polarization,
        candidate_uncertainty_null1=candidate_uncertainty_null1,
        candidate_uncertainty_null2=candidate_uncertainty_null2,
        reference_polarization=merged.polarization,
        reference_null1=merged.null1,
        reference_null2=merged.null2,
        reference_uncertainty=merged.uncertainty,
        comparison_uncertainty_polarization=np.hypot(
            merged.uncertainty, candidate_uncertainty_polarization
        ),
        comparison_uncertainty_null1=np.hypot(
            merged.uncertainty, candidate_uncertainty_null1
        ),
        comparison_uncertainty_null2=np.hypot(
            merged.uncertainty, candidate_uncertainty_null2
        ),
        mask=mask,
        r_band_median=np.asarray(np.median(raw_polarization[r_band])),
    )
    return {
        "label": label,
        "candidate_product": str(candidate_path),
        "reference_product_id": group.polarization_product_id,
        "valid_samples": int(np.count_nonzero(mask)),
        "r_band_median": float(np.median(raw_polarization[r_band])),
        "comparison_continuum": "0.5-nm candidate-reference median baseline",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build external CADC regression bundles from replay outputs"
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--ad-replay", type=Path, required=True)
    parser.add_argument("--hr-replay", type=Path, required=True)
    parser.add_argument("--hd-replay", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cache = validate_external_cache(args.cache_dir)
    destination = _outside_repository(args.candidate_dir)
    destination.mkdir(parents=True, exist_ok=True)
    replay_roots = {
        "ad_replay": _outside_repository(args.ad_replay),
        "hr_replay": _outside_repository(args.hr_replay),
        "hd_replay": _outside_repository(args.hd_replay),
    }
    ad_manifest = load_manifest(_manifest_for_label("Q"))
    l2_results = [
        _build_l2_bundle(
            raw_product_id=raw_product_id,
            intensity_product_id=intensity_product_id,
            replay_root=replay_roots["ad_replay"],
            cache=cache,
            manifest=ad_manifest,
            destination=destination / "l2" / f"{raw_product_id}.npz",
        )
        for group in GROUPS.values()
        for raw_product_id, intensity_product_id in zip(
            group.raw_product_ids, group.intensity_product_ids, strict=True
        )
    ]
    l3_results = [
        _build_l3_bundle(
            label=label,
            group=group,
            replay_root=replay_roots[replay_key],
            cache=cache,
            destination=destination / "l3" / f"{label}.npz",
        )
        for label, group, replay_key in L3_DATASETS
    ]
    receipt = destination / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "scope": "ad-leo-and-standard-stars",
                "l2_products": l2_results,
                "l3_products": l3_results,
                "production_inputs": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(receipt)


if __name__ == "__main__":
    main()
