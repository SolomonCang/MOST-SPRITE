from __future__ import annotations

import numpy as np
import pytest
from most_sprite.products.preview import downsample_image


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
