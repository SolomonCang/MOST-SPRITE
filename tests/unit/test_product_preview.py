from __future__ import annotations

import numpy as np
import pytest
from most_sprite.products.preview import downsample_image, order_trace_annotations


def test_downsample_image_preserves_aspect_and_narrow_bright_features() -> None:
    image = np.zeros((12, 24), dtype=np.float64)
    image[3, 5] = 1200.0
    image[10, 21] = 800.0

    preview = downsample_image(image, max_width=6, max_height=3)

    assert preview.shape == (3, 6)
    assert 1200.0 in preview
    assert 800.0 in preview


def test_downsample_image_keeps_non_finite_only_blocks_missing() -> None:
    image = np.full((4, 4), np.nan)
    image[0, 0] = 1.0

    preview = downsample_image(image, max_width=2, max_height=2)

    assert preview[0, 0] == 1.0
    assert np.isnan(preview[1, 1])


@pytest.mark.parametrize("shape", [(0, 3), (3, 0), (2, 2, 2)])
def test_downsample_image_rejects_invalid_shapes(shape: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        downsample_image(np.empty(shape))


def test_order_trace_annotations_include_every_identified_order() -> None:
    annotations = order_trace_annotations(
        np.asarray([22, 23, 24], dtype=np.int32),
        np.asarray([[0.0, 2.0], [0.0, 9.5], [0.0, 17.0]]),
        trace_shape=(20, 100),
        sample_count=8,
    )

    assert [item["order"] for item in annotations] == [22, 23, 24]
    assert all(len(item["points"]) == 8 for item in annotations)
    assert annotations[0]["points"][0] == [0.0, pytest.approx(2 / 19, abs=1e-6)]
    assert annotations[-1]["points"][-1] == [1.0, pytest.approx(17 / 19, abs=1e-6)]


def test_order_trace_annotations_can_map_canonical_traces_to_raw_image() -> None:
    def transpose_to_raw(
        dispersion: np.ndarray, center: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        return center + 4, dispersion + 2

    annotations = order_trace_annotations(
        np.asarray([57], dtype=np.int32),
        np.asarray([[0.0, 5.0]]),
        trace_shape=(12, 20),
        image_shape=(24, 18),
        coordinate_mapper=transpose_to_raw,
        sample_count=4,
    )

    assert annotations[0]["points"][0] == [
        pytest.approx(9 / 17, abs=1e-6),
        pytest.approx(2 / 23, abs=1e-6),
    ]
    assert annotations[0]["points"][-1] == [
        pytest.approx(9 / 17, abs=1e-6),
        pytest.approx(21 / 23, abs=1e-6),
    ]
