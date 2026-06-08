from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ChartImageScaleResult:
    image: np.ndarray
    scale: float
    original_width: int
    original_height: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "width": self.width,
            "height": self.height,
        }


def upscale_small_chord_chart_image(
    image: np.ndarray,
    *,
    min_width: int = 1200,
    min_height: int = 1400,
    max_scale: float = 2.0,
) -> ChartImageScaleResult:
    height, width = image.shape[:2]
    scale = max(1.0, min_width / width, min_height / height)
    scale = min(max_scale, scale)

    if scale == 1.0:
        return ChartImageScaleResult(
            image=image,
            scale=1.0,
            original_width=width,
            original_height=height,
            width=width,
            height=height,
        )

    scaled_image = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )
    scaled_height, scaled_width = scaled_image.shape[:2]
    return ChartImageScaleResult(
        image=scaled_image,
        scale=scale,
        original_width=width,
        original_height=height,
        width=scaled_width,
        height=scaled_height,
    )
