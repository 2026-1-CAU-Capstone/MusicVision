from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

OVERLAY_FILENAME = "chord_assignment_overlay.png"

MEASURE_COLOUR = (50, 100, 255)
ASSIGNED_CHORD_COLOUR = (30, 180, 30)
FILTERED_HIT_COLOUR = (255, 140, 0)
REJECTED_HIT_COLOUR = (220, 50, 50)


def write_chord_assignment_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    ocr_diagnostics: dict[str, Any],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay = render_chord_assignment_overlay(
        image=image,
        pages=pages,
        ocr_diagnostics=ocr_diagnostics,
    )
    overlay_path = output_dir / OVERLAY_FILENAME
    cv2.imwrite(str(overlay_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    return overlay_path


def render_chord_assignment_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    ocr_diagnostics: dict[str, Any],
) -> np.ndarray:
    """
    Render the current image-only assignment state in processed-image coordinates.

    The overlay is intentionally diagnostic rather than presentation-oriented:
    blue shows measure geometry, green shows assigned chords, orange shows
    chord-like OCR hits filtered by visual context, and red shows OCR rejects.
    """
    if len(image.shape) == 2:
        vis = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    else:
        vis = image.copy()

    page = pages[0] if pages else {"systems": []}
    systems = page.get("systems") or []

    measure_count = 0
    assigned_chord_count = 0
    for system in systems:
        for measure in system.get("measures") or []:
            measure_count += 1
            _draw_bbox(
                vis,
                measure.get("bbox"),
                colour=MEASURE_COLOUR,
                thickness=1,
            )
            bbox = measure.get("bbox")
            if _is_bbox(bbox):
                x0, y0, _x1, _y1 = [int(round(value)) for value in bbox]
                cv2.putText(
                    vis,
                    f"m{measure.get('index', '?')}",
                    (x0 + 3, max(y0 - 5, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.42,
                    MEASURE_COLOUR,
                    1,
                    cv2.LINE_AA,
                )

            for chord in measure.get("chords") or []:
                assigned_chord_count += 1
                _draw_bbox(
                    vis,
                    chord.get("bbox"),
                    colour=ASSIGNED_CHORD_COLOUR,
                    thickness=2,
                )
                bbox = chord.get("bbox")
                if _is_bbox(bbox):
                    x0, y0, _x1, _y1 = [int(round(value)) for value in bbox]
                    label = (
                        f"m{measure.get('index', '?')} "
                        f"b{chord.get('beat', '?')}: {chord.get('text_norm', '')}"
                    )
                    cv2.putText(
                        vis,
                        label,
                        (x0, max(y0 - 5, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.42,
                        ASSIGNED_CHORD_COLOUR,
                        1,
                        cv2.LINE_AA,
                    )

    filtered_hits = ocr_diagnostics.get("filtered_hits") or []
    for hit in filtered_hits:
        _draw_bbox(
            vis,
            hit.get("bbox"),
            colour=FILTERED_HIT_COLOUR,
            thickness=2,
        )
        _draw_hit_label(
            vis,
            hit,
            colour=FILTERED_HIT_COLOUR,
            prefix="filtered",
        )

    rejected_hits = ocr_diagnostics.get("rejected_hits") or []
    for hit in rejected_hits:
        _draw_bbox(
            vis,
            hit.get("bbox"),
            colour=REJECTED_HIT_COLOUR,
            thickness=1,
        )
        _draw_hit_label(
            vis,
            hit,
            colour=REJECTED_HIT_COLOUR,
            prefix="reject",
        )

    legend = [
        (MEASURE_COLOUR, f"Measures: {measure_count}"),
        (ASSIGNED_CHORD_COLOUR, f"Assigned chords: {assigned_chord_count}"),
        (FILTERED_HIT_COLOUR, f"Filtered hits: {len(filtered_hits)}"),
        (REJECTED_HIT_COLOUR, f"OCR rejects: {len(rejected_hits)}"),
    ]
    assignment_source = page.get("assignment_source")
    if assignment_source:
        legend.append(((40, 40, 40), f"Assignment source: {assignment_source}"))

    for index, (colour, text) in enumerate(legend):
        cv2.putText(
            vis,
            text,
            (10, 22 + index * 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            colour,
            1,
            cv2.LINE_AA,
        )

    return vis


def _draw_bbox(
    image: np.ndarray,
    bbox: Any,
    *,
    colour: tuple[int, int, int],
    thickness: int,
) -> None:
    if not _is_bbox(bbox):
        return
    x0, y0, x1, y1 = [int(round(value)) for value in bbox]
    cv2.rectangle(image, (x0, y0), (x1, y1), colour, thickness)


def _draw_hit_label(
    image: np.ndarray,
    hit: dict[str, Any],
    *,
    colour: tuple[int, int, int],
    prefix: str,
) -> None:
    bbox = hit.get("bbox")
    if not _is_bbox(bbox):
        return
    x0, y0, _x1, _y1 = [int(round(value)) for value in bbox]
    text = _truncate(str(hit.get("text_norm") or hit.get("text") or ""), limit=18)
    label = f"{prefix}: {text}"
    cv2.putText(
        image,
        label,
        (x0, max(y0 - 5, 14)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        colour,
        1,
        cv2.LINE_AA,
    )


def _is_bbox(value: Any) -> bool:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return False
    return all(isinstance(component, int | float) for component in value)


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"
