from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from pipeline.chords.easyocr_backend import _get_reader
from pipeline.chords.ocr_common import preprocess_for_ocr


@dataclass(frozen=True)
class OCRToken:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None = None
    source: str = "page_ocr"

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": [float(value) for value in self.bbox],
            "confidence": self.confidence,
            "source": self.source,
        }


def extract_chart_ocr_tokens(
    image: np.ndarray,
    *,
    min_confidence: float = 0.10,
    gpu: bool = False,
    ocr_scale: float = 2.0,
) -> tuple[list[OCRToken], list[dict[str, Any]]]:
    processed = preprocess_for_ocr(image, scale=ocr_scale)
    reader = _get_reader(gpu=gpu)
    results = reader.readtext(processed, detail=1, paragraph=False)
    inverse_scale = 1.0 / ocr_scale

    tokens: list[OCRToken] = []
    rejects: list[dict[str, Any]] = []

    for points, text, confidence in results:
        raw_text = (text or "").strip()
        if not raw_text:
            continue

        confidence_value = float(confidence)
        xs = [point[0] * inverse_scale for point in points]
        ys = [point[1] * inverse_scale for point in points]
        bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))

        if confidence_value < min_confidence:
            rejects.append(
                {
                    "text": raw_text,
                    "bbox": list(bbox),
                    "confidence": confidence_value,
                    "reason": (
                        f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                    ),
                }
            )
            continue

        tokens.append(
            OCRToken(
                text=raw_text,
                bbox=bbox,
                confidence=confidence_value,
                source="page_ocr",
            )
        )

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects


def extract_chart_cell_ocr_tokens(
    image: np.ndarray,
    rows: list[Any],
    *,
    min_confidence: float = 0.05,
    gpu: bool = False,
    ocr_scale: float = 2.0,
) -> tuple[list[OCRToken], list[dict[str, Any]]]:
    reader = _get_reader(gpu=gpu)
    tokens: list[OCRToken] = []
    rejects: list[dict[str, Any]] = []

    row_list = list(rows)
    for row_position, row in enumerate(row_list):
        boundaries = getattr(row, "boundaries", [])
        for col_index, (left, right) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            x0 = int(max(0, float(left.x) + 8))
            x1 = int(min(image.shape[1], float(right.x) - 8))
            next_y_top = (
                float(getattr(row_list[row_position + 1], "y_top"))
                if row_position + 1 < len(row_list)
                else float(image.shape[0])
            )
            y0 = int(max(0, float(row.y_top) - 35))
            y1 = int(min(image.shape[0], next_y_top - 8, float(row.y_bottom) + 80))
            if x1 <= x0 or y1 <= y0:
                continue

            crop = image[y0:y1, x0:x1].copy()
            for region_name, xa, xb, ya, yb in _cell_ocr_regions():
                crop_height, crop_width = crop.shape[:2]
                rx0 = int(crop_width * xa)
                rx1 = int(crop_width * xb)
                ry0 = int(crop_height * ya)
                ry1 = int(crop_height * yb)
                subcrop = crop[ry0:ry1, rx0:rx1]
                if subcrop.size == 0:
                    continue

                processed = preprocess_for_ocr(subcrop, scale=ocr_scale)
                inverse_scale = 1.0 / ocr_scale
                results = reader.readtext(processed, detail=1, paragraph=False)

                for points, text, confidence in results:
                    raw_text = (text or "").strip()
                    if not raw_text:
                        continue

                    confidence_value = float(confidence)
                    xs = [x0 + rx0 + point[0] * inverse_scale for point in points]
                    ys = [y0 + ry0 + point[1] * inverse_scale for point in points]
                    bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
                    record = {
                        "text": raw_text,
                        "bbox": list(bbox),
                        "confidence": confidence_value,
                        "row_index": getattr(row, "index", None),
                        "col_index": col_index,
                        "region": region_name,
                        "source": "cell_ocr",
                    }

                    if confidence_value < min_confidence:
                        rejects.append(
                            {
                                **record,
                                "reason": (
                                    f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                                ),
                            }
                        )
                        continue

                    tokens.append(
                        OCRToken(
                            text=raw_text,
                            bbox=bbox,
                            confidence=confidence_value,
                            source="cell_ocr",
                        )
                    )

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects


def _cell_ocr_regions() -> list[tuple[str, float, float, float, float]]:
    return [
        ("full", 0.0, 1.0, 0.0, 1.0),
        ("top", 0.0, 1.0, 0.0, 0.70),
        ("bottom", 0.0, 1.0, 0.30, 1.0),
        ("left", 0.0, 0.58, 0.0, 1.0),
        ("right", 0.42, 1.0, 0.0, 1.0),
        ("low", 0.0, 1.0, 0.55, 1.0),
    ]
