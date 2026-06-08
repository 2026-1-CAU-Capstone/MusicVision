from __future__ import annotations

import numpy as np

from pipeline.chord_charts.image_preprocessing import upscale_small_chord_chart_image


def test_upscale_small_chord_chart_image_doubles_low_resolution_image() -> None:
    image = np.zeros((720, 599, 3), dtype=np.uint8)

    result = upscale_small_chord_chart_image(image)

    assert result.scale == 2.0
    assert result.original_width == 599
    assert result.original_height == 720
    assert result.width == 1198
    assert result.height == 1440
    assert result.image.shape == (1440, 1198, 3)


def test_upscale_small_chord_chart_image_leaves_large_image_unchanged() -> None:
    image = np.zeros((1500, 1300, 3), dtype=np.uint8)

    result = upscale_small_chord_chart_image(image)

    assert result.scale == 1.0
    assert result.image is image
    assert result.width == 1300
    assert result.height == 1500
