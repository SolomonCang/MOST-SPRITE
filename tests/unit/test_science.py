from __future__ import annotations

from itertools import permutations

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from most_sprite.configuration import SIGN_VECTORS
from most_sprite.domain.enums import DQBit
from most_sprite.pipeline.nonpolar import subtract_sky
from most_sprite.pipeline.polarimetry import BeamSpectrum, demodulate_group


def polar_group(
    polarization: float,
    *,
    samples: int = 1024,
    photons: float = 1e8,
    noisy: bool = False,
    seed: int = 20260826,
) -> list[BeamSpectrum]:
    wave = np.linspace(400.0, 700.0, samples, dtype=np.float64)
    rng = np.random.default_rng(seed)
    result = []
    for index, sign in enumerate(SIGN_VECTORS["science"]):
        expected_o = np.full(samples, photons * (1 + sign * polarization), dtype=np.float64)
        expected_e = np.full(samples, photons * (1 - sign * polarization), dtype=np.float64)
        if noisy:
            o_flux = rng.poisson(expected_o).astype(np.float64)
            e_flux = rng.poisson(expected_e).astype(np.float64)
            o_variance = expected_o
            e_variance = expected_e
        else:
            o_flux = expected_o
            e_flux = expected_e
            o_variance = np.zeros(samples, dtype=np.float64)
            e_variance = np.zeros(samples, dtype=np.float64)
        result.append(
            BeamSpectrum(
                wavelength=wave,
                o_flux=o_flux,
                e_flux=e_flux,
                o_variance=o_variance,
                e_variance=e_variance,
                dq=np.zeros(samples, dtype=np.uint32),
                sub_index=index + 1,
                exposure_id=str(index),
            )
        )
    return result


def test_noiseless_polarimetric_injection_reaches_machine_precision() -> None:
    result = demodulate_group(polar_group(0.0025))
    assert np.max(np.abs(result.polarization - 0.0025)) <= 1e-10
    assert np.max(np.abs(result.null1)) <= 1e-10
    assert np.max(np.abs(result.null2)) <= 1e-10
    assert np.max(np.abs(result.difference_check - result.polarization)) <= 1e-10


@given(st.floats(min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False))
def test_noiseless_ratio_demodulation_property(polarization: float) -> None:
    result = demodulate_group(polar_group(polarization, samples=32))
    assert np.max(np.abs(result.polarization - polarization)) <= 1e-10


def test_subexposure_permutations_are_canonicalized_by_index() -> None:
    exposures = polar_group(0.003, samples=16)
    expected = demodulate_group(exposures)
    for order in permutations(exposures):
        actual = demodulate_group(list(order))
        assert np.array_equal(actual.polarization, expected.polarization)
        assert np.array_equal(actual.null1, expected.null1)
        assert np.array_equal(actual.null2, expected.null2)


def test_beam_exchange_flips_the_polarization_sign() -> None:
    exposures = polar_group(0.003, samples=16)
    expected = demodulate_group(exposures)
    for exposure in exposures:
        exposure.o_flux, exposure.e_flux = exposure.e_flux.copy(), exposure.o_flux.copy()
        exposure.o_variance, exposure.e_variance = (
            exposure.e_variance.copy(),
            exposure.o_variance.copy(),
        )
    exchanged = demodulate_group(exposures)
    assert np.allclose(exchanged.polarization, -expected.polarization)


def test_science_and_null_vectors_are_orthogonal() -> None:
    vectors = [np.asarray(SIGN_VECTORS[key]) for key in ("science", "null1", "null2")]
    assert all(np.dot(left, right) == 0 for left, right in permutations(vectors, 2))


def test_high_signal_noise_bias_and_reported_uncertainty() -> None:
    result = demodulate_group(polar_group(-0.0015, noisy=True))
    assert abs(float(np.nanmedian(result.polarization)) + 0.0015) <= 1e-4
    assert float(np.nanmedian(result.err_polarization)) <= 1e-3
    assert abs(float(np.nanmean(result.null1))) <= 1e-4
    assert abs(float(np.nanmean(result.null2))) <= 1e-4


def test_reported_polarization_null_covariance_is_positive_semidefinite() -> None:
    result = demodulate_group(polar_group(0.004, samples=64, noisy=True))
    for index in range(result.wavelength.size):
        covariance = np.array(
            [
                [
                    result.err_polarization[index] ** 2,
                    result.covariance_p_null1[index],
                    result.covariance_p_null2[index],
                ],
                [
                    result.covariance_p_null1[index],
                    result.err_null1[index] ** 2,
                    result.covariance_null1_null2[index],
                ],
                [
                    result.covariance_p_null2[index],
                    result.covariance_null1_null2[index],
                    result.err_null2[index] ** 2,
                ],
            ]
        )
        assert float(np.min(np.linalg.eigvalsh(covariance))) >= -1e-18


def test_single_frame_contamination_marks_corresponding_null_spectra() -> None:
    exposures = polar_group(0.001, photons=1e7)
    for exposure in exposures:
        exposure.o_variance[:] = exposure.o_flux
        exposure.e_variance[:] = exposure.e_flux
    exposures[0].o_flux[100:110] *= 1.1
    result = demodulate_group(exposures, null_sigma_threshold=5.0)
    assert np.any(result.dq[100:110] & DQBit.NULL1_EXCESS)
    assert np.any(result.dq[100:110] & DQBit.NULL2_EXCESS)


def test_nonpolar_propagates_sky_and_alpha_variance() -> None:
    wave = np.linspace(500.0, 501.0, 8)
    target = np.full(8, 100.0)
    sky = np.full(8, 10.0)
    alpha = np.full(8, 1.2)
    result = subtract_sky(
        wave,
        target,
        sky,
        alpha,
        np.full(8, 4.0),
        np.full(8, 2.0),
        np.full(8, 0.01),
    )
    assert np.allclose(result.intensity, 88.0)
    assert np.allclose(result.err_intensity**2, 4.0 + 1.2**2 * 2.0 + 10.0**2 * 0.01)
    assert result.background_subtracted


def test_invalid_sky_yields_degraded_target_without_fake_subtraction() -> None:
    wave = np.linspace(500.0, 501.0, 8)
    target = np.full(8, 100.0)
    result = subtract_sky(
        wave,
        target,
        None,
        np.ones(8),
        np.ones(8),
        None,
        np.zeros(8),
    )
    assert np.array_equal(result.intensity, target)
    assert np.all(result.dq & DQBit.SKY_INVALID)
    assert not result.background_subtracted
