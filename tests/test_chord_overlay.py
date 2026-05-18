from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pipeline.chords.overlay import (
    ASSIGNED_CHORD_COLOUR,
    FILTERED_HIT_COLOUR,
    MEASURE_COLOUR,
    REJECTED_HIT_COLOUR,
    render_chord_assignment_overlay,
    write_chord_assignment_overlay,
)


def _sample_pages() -> list[dict]:
    return [
        {
            "page": 1,
            "assignment_source": "homr_geometry",
            "systems": [
                {
                    "index": 1,
                    "measures": [
                        {
                            "index": 1,
                            "bbox": [20, 80, 240, 140],
                            "chords": [
                                {
                                    "text_norm": "Dm7",
                                    "bbox": [140, 20, 170, 45],
                                    "beat": 1,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]


def _sample_diagnostics() -> dict:
    return {
        "filtered_hits": [
            {"text": "8", "text_norm": "B", "bbox": [220, 20, 250, 45]},
        ],
        "rejected_hits": [
            {"text": "Verse", "bbox": [180, 20, 210, 45]},
        ],
    }


def test_overlay_renders_measure_assignment_and_ocr_decisions() -> None:
    image = np.full((160, 260, 3), 255, dtype=np.uint8)

    overlay = render_chord_assignment_overlay(
        image=image,
        pages=_sample_pages(),
        ocr_diagnostics=_sample_diagnostics(),
    )

    assert tuple(overlay[80, 100]) == MEASURE_COLOUR
    assert tuple(overlay[20, 150]) == ASSIGNED_CHORD_COLOUR
    assert tuple(overlay[20, 230]) == FILTERED_HIT_COLOUR
    assert tuple(overlay[20, 190]) == REJECTED_HIT_COLOUR


def test_overlay_writer_saves_png(tmp_path: Path) -> None:
    image = np.full((160, 260, 3), 255, dtype=np.uint8)

    overlay_path = write_chord_assignment_overlay(
        image=image,
        pages=_sample_pages(),
        ocr_diagnostics=_sample_diagnostics(),
        output_dir=tmp_path,
    )

    assert overlay_path.name == "chord_assignment_overlay.png"
    assert overlay_path.exists()
    saved = cv2.imread(str(overlay_path))
    assert saved is not None
