from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from pipeline.chords.grammar import looks_like_chord_ocr, normalize_text
from pipeline.chords.models import ChordToken


def load_rgb_image(image_path: Path) -> np.ndarray:
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def preprocess_for_ocr(image: np.ndarray, scale: float = 2.0) -> np.ndarray:
    height, width = image.shape[:2]

    if scale != 1.0:
        image = cv2.resize(
            image,
            (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_CUBIC,
        )

    image = cv2.fastNlMeansDenoisingColored(
        image,
        None,
        h=7,
        hColor=7,
        templateWindowSize=7,
        searchWindowSize=21,
    )
    blur = cv2.GaussianBlur(image, (0, 0), sigmaX=2.0)
    return cv2.addWeighted(image, 1.5, blur, -0.5, 0)


def try_split_merged_token(
    raw_text: str,
    bbox: tuple[float, float, float, float],
) -> list[ChordToken]:
    text = re.sub(r"\s+", "", raw_text)
    if len(text) < 4:
        return []

    x0, y0, x1, y1 = bbox
    total_width = x1 - x0
    best_split: tuple[int, str, str] | None = None

    for split_index in range(2, len(text) - 1):
        left = text[:split_index]
        right = text[split_index:]
        left_ok, left_corrected = looks_like_chord_ocr(left)
        right_ok, right_corrected = looks_like_chord_ocr(right)

        if left_ok and right_ok:
            if best_split is None or split_index > best_split[0]:
                best_split = (split_index, left_corrected, right_corrected)

    if best_split is None:
        return []

    split_index, left_corrected, right_corrected = best_split
    midpoint_x = x0 + total_width * (split_index / len(text))
    return [
        ChordToken(
            text_raw=text[:split_index],
            text_norm=normalize_text(left_corrected),
            bbox=(x0, y0, midpoint_x, y1),
        ),
        ChordToken(
            text_raw=text[split_index:],
            text_norm=normalize_text(right_corrected),
            bbox=(midpoint_x, y0, x1, y1),
        ),
    ]
