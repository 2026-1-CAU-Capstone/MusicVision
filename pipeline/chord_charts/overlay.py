from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


CHORD_CHART_OVERLAY_FILENAME = "chord_chart_overlay.png"
MEASURE_COLOUR = (40, 120, 220)
CHORD_COLOUR = (30, 170, 60)
SYMBOL_COLOUR = (220, 140, 30)
NAVIGATION_COLOUR = (190, 60, 190)


def write_chord_chart_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    overlay = render_chord_chart_overlay(image=image, pages=pages)
    output_path = output_dir / CHORD_CHART_OVERLAY_FILENAME
    cv2.imwrite(str(output_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    return output_path


def render_chord_chart_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
) -> np.ndarray:
    overlay = image.copy()

    for page in pages:
        for system in page.get("systems") or []:
            for measure in system.get("measures") or []:
                _draw_box(overlay, measure.get("bbox"), MEASURE_COLOUR, thickness=2)
                label = str(measure.get("index", "?"))
                _draw_text(overlay, label, measure.get("bbox"), MEASURE_COLOUR)

                for chord in measure.get("chords") or []:
                    _draw_box(overlay, chord.get("bbox"), CHORD_COLOUR, thickness=3)
                    _draw_text(
                        overlay,
                        str(chord.get("text_norm", "")),
                        chord.get("bbox"),
                        CHORD_COLOUR,
                    )

                for symbol in measure.get("symbols") or []:
                    _draw_box(overlay, symbol.get("bbox"), SYMBOL_COLOUR, thickness=3)

                for navigation in measure.get("navigation") or []:
                    _draw_box(
                        overlay,
                        navigation.get("bbox"),
                        NAVIGATION_COLOUR,
                        thickness=3,
                    )

    return overlay


def _draw_box(
    image: np.ndarray,
    bbox: object,
    colour: tuple[int, int, int],
    *,
    thickness: int,
) -> None:
    if not _valid_bbox(bbox):
        return
    x0, y0, x1, y1 = [int(round(float(value))) for value in bbox]
    cv2.rectangle(image, (x0, y0), (x1, y1), colour, thickness)


def _draw_text(
    image: np.ndarray,
    text: str,
    bbox: object,
    colour: tuple[int, int, int],
) -> None:
    if not text or not _valid_bbox(bbox):
        return
    x0, y0, _x1, _y1 = [int(round(float(value))) for value in bbox]
    cv2.putText(
        image,
        text,
        (x0 + 4, max(16, y0 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        colour,
        2,
        cv2.LINE_AA,
    )


def _valid_bbox(bbox: object) -> bool:
    return (
        isinstance(bbox, list | tuple)
        and len(bbox) == 4
        and all(isinstance(value, int | float) for value in bbox)
    )
