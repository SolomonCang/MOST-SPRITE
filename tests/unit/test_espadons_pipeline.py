from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from most_sprite.calibration.bundle import (
    ESPaDOnSCalibrationBundle,
    read_calibration_bundle,
    write_calibration_bundle,
)
from most_sprite.domain.enums import DataMode, DQBit
from most_sprite.errors import SpriteError
from most_sprite.pipeline.echelle.espadons import (
    ESPaDOnSTraceSet,
    _select_olapa_polarimetric_anchors,
)
from most_sprite.pipeline.echelle.imageproc import combine_calibration
from most_sprite.pipeline.echelle.models import (
    CalibrationFrame,
    SpectrumChannel,
    SpectrumSet,
    TraceModel,
    WavelengthSolution,
)
from most_sprite.pipeline.instruments.base import RawDescriptor
from most_sprite.pipeline.instruments.espadons import (
    ESPaDOnSAdapter,
    parse_fits_section,
)
from most_sprite.pipeline.polarimetry import BeamSpectrum, demodulate_group
from most_sprite.pipeline.wavelength import resample_common_grid
from most_sprite.pipeline.wavelength.espadons import (
    _BOOTSTRAP_COEFFICIENTS,
    _features,
)


def _write_raw(
    path: Path,
    *,
    detector: str = "OLAPA",
    comment_sequence: str = "Q exposure 1, sequence 1",
) -> np.ndarray:
    raw = np.array(
        [
            [11, 12, 13, 14, 10, 10],
            [21, 22, 23, 24, 20, 20],
            [31, 32, 33, 34, 30, 30],
        ],
        dtype=np.uint16,
    )
    header = fits.Header(
        {
            "DETECTOR": detector,
            "OBSTYPE": "OBJECT",
            "OBJECT": "TEST STAR",
            "DATE-OBS": "2026-08-27",
            "UTC-OBS": "01:02:03",
            "EXPTIME": 10.0,
            "CMMTSEQ": comment_sequence,
            "DATASEC": "[1:4,1:3]",
            "BIASSEC": "[5:6,1:3]",
            "GAIN": 1.0,
            "RDNOISE": 2.0,
        }
    )
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(raw, header=header)]).writeto(path)
    return raw


def test_fits_sections_are_one_indexed_and_honor_reversed_axes() -> None:
    values = np.arange(20).reshape(4, 5)
    section = parse_fits_section("[4:2,3:1]", shape=values.shape)
    assert np.array_equal(section.extract(values), values[0:3, 1:4][::-1, ::-1])
    with pytest.raises(SpriteError, match="one-indexed"):
        parse_fits_section("[0:2,1:3]", shape=values.shape)
    with pytest.raises(SpriteError, match="exceeds image shape"):
        parse_fits_section("[1:6,1:3]", shape=values.shape)


def test_calibration_combine_is_tiled_and_rejects_outliers() -> None:
    shape = (5, 4)
    frame = CalibrationFrame(
        data=np.full(shape, 10.0),
        variance=np.ones(shape),
        dq=np.zeros(shape, dtype=np.uint32),
        unit="electron",
    )
    result = combine_calibration(
        [frame, np.full(shape, 10.0), np.full(shape, 100.0)],
        {
            "read_noise_e": 1.0,
            "working_memory_bytes": 3 * shape[1] * 8 * 4,
            "config_version": "test-v1",
        },
    )
    assert np.allclose(result.data, 10.0)
    assert np.allclose(result.variance, 0.0)
    assert np.all(result.dq == 0)
    assert result.unit == "electron"
    assert result.provenance["tile_rows"] == 1


def test_empty_primary_hdu1_is_read_and_transformed_to_canonical_axes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "0000001o.fits.fz"
    raw = _write_raw(path)
    adapter = ESPaDOnSAdapter()
    descriptor = adapter.inspect(path, relative_path=path.name)
    canonical, provenance, profile = adapter.canonical_image(path)
    frame, _, _ = adapter.preprocess(path)

    assert descriptor.image_hdu == 1
    assert descriptor.detector == "OLAPA"
    assert descriptor.mode is DataMode.POL_Q
    assert descriptor.sub_index == 1
    assert descriptor.source_format == "CFHT_FITS_FPACK"
    assert np.array_equal(canonical, raw[:, :4].T)
    assert profile.canonical_shape == (4, 3)
    assert frame.data.shape == (4, 3)
    assert np.allclose(frame.data, np.ones((4, 3)) * np.arange(1, 5)[:, None])
    assert np.allclose(frame.variance, np.clip(frame.data, 0, None) + 4.0)
    assert provenance["source_image_hdu"] == 1
    assert "transpose" in provenance["axis_transform"]


def test_eev1_is_rejected_instead_of_using_olapa_parameters(tmp_path: Path) -> None:
    path = tmp_path / "0000001o.fits.fz"
    _write_raw(path, detector="EEV1")
    with pytest.raises(SpriteError) as error:
        ESPaDOnSAdapter().inspect(path, relative_path=path.name)
    assert error.value.code == "UNSUPPORTED_DETECTOR"


def _descriptor(sub_index: int, minute: int) -> RawDescriptor:
    return RawDescriptor(
        path=Path(f"{minute:02d}{sub_index}o.fits.fz"),
        relative_path=f"{minute:02d}{sub_index}o.fits.fz",
        size=1,
        sha256=f"{minute:02d}{sub_index}".ljust(64, "0"),
        role="SCIENCE",
        instrument="ESPADONS",
        detector="OLAPA",
        source_format="CFHT_FITS_FPACK",
        image_hdu=1,
        mode=DataMode.POL_Q,
        stokes="Q",
        sub_index=sub_index,
        sequence_number=None,
        target_name="REPEATED",
        exposure_time=10.0,
        observing_night="2026-08-27",
        observed_at=f"2026-08-27T01:{minute:02d}:{sub_index:02d}",
        readout_mode="1|1|A|SLOW",
    )


def test_repeated_groups_reset_sub_indices_to_one_through_four() -> None:
    descriptors = [
        *[_descriptor(index, 10) for index in range(1, 5)],
        *[_descriptor(index, 20) for index in range(1, 5)],
    ]
    groups = ESPaDOnSAdapter().group_science(descriptors)
    assert [group["sequence_number"] for group in groups] == [1, 2]
    assert [group["sub_indices"] for group in groups] == [[1, 2, 3, 4]] * 2
    assert all(len(group["artifacts"]) == 4 for group in groups)


def test_olapa_trace_excludes_interleaved_physical_order_21() -> None:
    locations = [(float(value), float(value - 2), float(value + 2)) for value in range(4)]
    anchors = _select_olapa_polarimetric_anchors(
        locations,
        expected_orders=3,
    )

    assert [anchor[0] for anchor in anchors] == [0.0, 2.0, 3.0]
    assert _select_olapa_polarimetric_anchors(
        locations[:3], expected_orders=3
    ) == locations[:3]

    with pytest.raises(ValueError, match="expected 3 or 4"):
        _select_olapa_polarimetric_anchors(
            locations[:2],
            expected_orders=3,
        )


def test_olapa_wavelength_bootstrap_has_canonical_orientation_and_scale() -> None:
    pixels = np.array([0.0, 2304.0, 4607.0])
    normalized_pixels = (pixels - (4608 - 1) / 2.0) / 4608
    order = 34.0
    order_coordinate = np.full(pixels.shape, (order - 41.5) / 19.5)
    wavelength = (
        _features(normalized_pixels, order_coordinate, 2)
        @ _BOOTSTRAP_COEFFICIENTS
        / order
    )

    assert np.all(np.diff(wavelength) > 0)
    assert np.allclose(wavelength, [651.6, 666.0, 678.3], atol=0.2)


@pytest.mark.parametrize(
    ("mode", "expected_sign"),
    [(DataMode.POL_Q, 1.0), (DataMode.POL_U, -1.0), (DataMode.POL_V, 1.0)],
)
def test_cfht_q_u_v_output_sign_convention(
    mode: DataMode, expected_sign: float
) -> None:
    model = ESPaDOnSAdapter().demodulation_model(mode)
    assert model.science_signs == (-1, 1, 1, -1)
    assert model.version.endswith("ratio-log-cfht-sign-v2")
    wavelength = np.linspace(500.0, 501.0, 16)
    injected = 0.012
    exposures = []
    for sub_index, sign in enumerate(model.science_signs, start=1):
        ratio_log = 2.0 * np.arctanh(injected) * sign
        exposures.append(
            BeamSpectrum(
                wavelength=wavelength,
                o_flux=np.full(wavelength.shape, 1000.0 * np.exp(ratio_log / 2.0)),
                e_flux=np.full(wavelength.shape, 1000.0 * np.exp(-ratio_log / 2.0)),
                o_variance=np.ones(wavelength.shape),
                e_variance=np.ones(wavelength.shape),
                dq=np.zeros(wavelength.shape, dtype=np.uint32),
                sub_index=sub_index,
                config_version="espadons-olapa-v1",
            )
        )
    result = demodulate_group(exposures, model=model)
    assert np.allclose(result.polarization, expected_sign * injected)
    assert np.allclose(result.null1, 0.0)
    assert np.allclose(result.null2, 0.0)
    assert result.provenance["output_sign"] == expected_sign


def _single_order_spectrum() -> SpectrumSet:
    wavelength = np.array([0.5, 1.5, 2.5, 3.5])
    channel = SpectrumChannel(
        role="O_BEAM",
        order=np.full(4, 42, dtype=np.int32),
        pixel=np.arange(4, dtype=np.float64),
        wavelength=wavelength,
        flux=np.array([1.0, 2.0, 3.0, 4.0]),
        variance=np.ones(4),
        dq=np.array([0, DQBit.COSMIC_RAY, 0, 0], dtype=np.uint32),
        covariance_lag1=np.array([0.25, 0.25, 0.25, 0.0]),
        config_version="espadons-olapa-v1",
    )
    return SpectrumSet(
        channels={"O_BEAM": channel},
        config_version="espadons-olapa-v1",
        provenance={},
    )


def test_single_flux_conserving_resample_propagates_variance_covariance_and_dq() -> None:
    source = _single_order_spectrum()
    result = resample_common_grid(source, {42: np.array([1.0, 3.0])})
    channel = result.channels["O_BEAM"]
    assert np.allclose(channel.flux, [3.0, 7.0])
    assert np.isclose(np.sum(channel.flux), np.sum(source.channels["O_BEAM"].flux))
    assert np.allclose(channel.variance, [2.5, 2.5])
    assert np.allclose(channel.covariance_lag1, [0.25, 0.0])
    assert channel.dq[0] & DQBit.COSMIC_RAY
    assert result.provenance["common_grid_resampling_count"] == 1
    with pytest.raises(ValueError, match="only once"):
        resample_common_grid(result, {42: np.array([1.0, 3.0])})


def test_calibration_bundle_round_trip_preserves_role_order_models(tmp_path: Path) -> None:
    shape = (4, 5)
    frame = CalibrationFrame(
        data=np.arange(np.prod(shape), dtype=np.float64).reshape(shape),
        variance=np.ones(shape),
        dq=np.zeros(shape, dtype=np.uint32),
        unit="electron",
        config_version="espadons-olapa-v1",
    )
    combined = TraceModel(
        order_ids=np.array([42], dtype=np.int32),
        coefficients=np.array([[0.0, 2.0]]),
        widths=np.array([6.0]),
        config_version="espadons-olapa-v1",
    )
    trace_set = ESPaDOnSTraceSet(
        combined=combined,
        beams={
            "O_BEAM": replace(combined, coefficients=np.array([[0.0, 1.5]])),
            "E_BEAM": replace(combined, coefficients=np.array([[0.0, 2.5]])),
        },
        config_version="espadons-olapa-v1",
    )
    solution = WavelengthSolution(
        coefficients={42: np.array([0.01, 500.0])},
        residual_rms={42: 120.0},
        channel_coefficients={
            "O_BEAM": {42: np.array([0.01, 500.0])},
            "E_BEAM": {42: np.array([0.01, 500.001])},
        },
        wavelength_type="AIR",
        unit="nm",
        config_version="espadons-olapa-v1",
    )
    bundle = ESPaDOnSCalibrationBundle(
        master_bias=frame,
        master_flat=replace(frame, data=frame.data + 100.0),
        flat_response=np.ones(shape),
        flat_variance=np.full(shape, 0.01),
        flat_dq=np.zeros(shape, dtype=np.uint32),
        spatial_profile=np.ones((2, 1, 5)),
        trace_set=trace_set,
        wavelength_solution=solution,
        blaze={"O_BEAM": {42: np.ones(5)}, "E_BEAM": {42: np.ones(5)}},
        identified_lines=[
            {
                "order": 42,
                "pixel": 2.0,
                "wavelength_nm": 500.02,
                "residual_m_s": 12.0,
                "used": True,
            }
        ],
        qc={"passed": True},
        provenance={"source_commit": "4d91ead6"},
    )
    path = tmp_path / "calibration.fits"
    write_calibration_bundle(bundle, path)
    loaded = read_calibration_bundle(path)
    assert np.allclose(loaded.master_bias.data, frame.data)
    assert np.allclose(
        loaded.trace_set.beams["E_BEAM"].coefficients,
        trace_set.beams["E_BEAM"].coefficients,
    )
    assert np.allclose(
        loaded.wavelength_solution.channel_coefficients["E_BEAM"][42],
        solution.channel_coefficients["E_BEAM"][42],
    )
    assert loaded.identified_lines[0]["used"] is True
    assert loaded.qc == {"passed": True}
