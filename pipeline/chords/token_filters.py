from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from pipeline.chords.models import ChordToken

_SINGLE_ROOTS = set("ABCDEFG")
_STAFF_TOUCH_MARGIN_PX = 6.0
_CIRCLE_MIN_EXPANSION_RATIO = 1.15
_CIRCLE_MIN_ASPECT_RATIO = 0.75
_CIRCLE_MAX_ASPECT_RATIO = 1.35
_CIRCLE_MAX_EXPANSION_RATIO = 3.0


def filter_probable_non_chords(
    *,
    tokens: list[ChordToken],
    image: np.ndarray,
    geometry: dict[str, Any] | None,
) -> tuple[list[ChordToken], list[dict[str, Any]]]:
    kept: list[ChordToken] = []
    filtered: list[dict[str, Any]] = []

    for token in tokens:
        rehearsal_metrics = _circled_rehearsal_metrics(token, image)
        if rehearsal_metrics is not None:
            filtered.append(
                _serialize_filtered_token(
                    token,
                    reason="circled_rehearsal_mark",
                    metrics=rehearsal_metrics,
                )
            )
            continue

        staff_touch_metrics = _single_letter_staff_touch_metrics(token, geometry)
        if staff_touch_metrics is not None:
            filtered.append(
                _serialize_filtered_token(
                    token,
                    reason="single_letter_touches_staff",
                    metrics=staff_touch_metrics,
                )
            )
            continue

        kept.append(token)

    return kept, filtered


def serialize_token(token: ChordToken) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text_raw": token.text_raw,
        "text_norm": token.text_norm,
        "bbox": list(token.bbox),
    }
    if token.confidence is not None:
        payload["conf"] = float(token.confidence)
    return payload


def _serialize_filtered_token(
    token: ChordToken,
    *,
    reason: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        **serialize_token(token),
        "reason": reason,
        "metrics": metrics,
    }


def _circled_rehearsal_metrics(
    token: ChordToken,
    image: np.ndarray,
) -> dict[str, Any] | None:
    if token.text_norm not in _SINGLE_ROOTS:
        return None

    x0, y0, x1, y1 = token.bbox
    token_width = x1 - x0
    token_height = y1 - y0
    if token_width <= 0 or token_height <= 0:
        return None

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    pad = max(6, int(round(max(token_width, token_height) * 0.75)))
    roi_x0 = max(0, int(round(x0)) - pad)
    roi_y0 = max(0, int(round(y0)) - pad)
    roi_x1 = min(gray.shape[1], int(round(x1)) + pad + 1)
    roi_y1 = min(gray.shape[0], int(round(y1)) + pad + 1)
    roi = gray[roi_y0:roi_y1, roi_x0:roi_x1]
    if roi.size == 0:
        return None

    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _hierarchy = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    token_cx = (x0 + x1) / 2.0
    token_cy = (y0 + y1) / 2.0

    for contour in contours:
        local_x, local_y, width, height = cv2.boundingRect(contour)
        contour_x0 = float(roi_x0 + local_x)
        contour_y0 = float(roi_y0 + local_y)
        contour_x1 = contour_x0 + float(width)
        contour_y1 = contour_y0 + float(height)
        if not (
            contour_x0 <= token_cx <= contour_x1
            and contour_y0 <= token_cy <= contour_y1
        ):
            continue

        width_ratio = width / token_width
        height_ratio = height / token_height
        aspect_ratio = width / max(float(height), 1.0)
        if (
            width_ratio < _CIRCLE_MIN_EXPANSION_RATIO
            or height_ratio < _CIRCLE_MIN_EXPANSION_RATIO
            or width_ratio > _CIRCLE_MAX_EXPANSION_RATIO
            or height_ratio > _CIRCLE_MAX_EXPANSION_RATIO
            or aspect_ratio < _CIRCLE_MIN_ASPECT_RATIO
            or aspect_ratio > _CIRCLE_MAX_ASPECT_RATIO
        ):
            continue

        return {
            "contour_bbox": [contour_x0, contour_y0, contour_x1, contour_y1],
            "width_ratio": round(width_ratio, 3),
            "height_ratio": round(height_ratio, 3),
            "aspect_ratio": round(aspect_ratio, 3),
        }

    return None


def _single_letter_staff_touch_metrics(
    token: ChordToken,
    geometry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if token.text_norm not in _SINGLE_ROOTS or not geometry:
        return None

    systems = geometry.get("systems") or []
    usable_systems: list[tuple[int, tuple[float, float, float, float]]] = []
    for raw_system in systems:
        bbox = raw_system.get("bbox")
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        try:
            usable_systems.append(
                (
                    int(raw_system.get("index", len(usable_systems) + 1)),
                    tuple(float(value) for value in bbox),
                )
            )
        except (TypeError, ValueError):
            continue

    if not usable_systems:
        return None

    nearest_index, nearest_bbox = min(
        usable_systems,
        key=lambda item: abs(token.cy - ((item[1][1] + item[1][3]) / 2.0)),
    )
    bottom_to_staff_top = nearest_bbox[1] - token.bbox[3]
    if bottom_to_staff_top > _STAFF_TOUCH_MARGIN_PX:
        return None

    return {
        "nearest_system_index": nearest_index,
        "token_bottom_to_staff_top_px": round(bottom_to_staff_top, 3),
        "threshold_px": _STAFF_TOUCH_MARGIN_PX,
    }
