from __future__ import annotations

import numpy as np

from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.overlay import (
    CHORD_COLOUR,
    OCR_ACCEPTED_COLOUR,
    SCAN_ROOT_COLOUR,
    render_chord_chart_ocr_debug_overlay,
)


def test_chord_chart_ocr_debug_overlay_draws_inline_token_labels() -> None:
    image = np.full((120, 180, 3), 255, dtype=np.uint8)
    token = OCRToken(
        "Bb",
        (44.0, 50.0, 70.0, 68.0),
        0.82,
        "cell_ocr_targeted",
        row_index=1,
        col_index=1,
        measure_index=1,
        region="root",
    )
    pages = [
        {
            "systems": [
                {
                    "measures": [
                        {
                            "index": 1,
                            "bbox": [20.0, 40.0, 160.0, 90.0],
                            "chords": [
                                {
                                    "text_raw": "Bb",
                                    "text_norm": "Bb6",
                                    "bbox": [44.0, 50.0, 88.0, 72.0],
                                }
                            ],
                            "symbols": [],
                            "navigation": [],
                        }
                    ]
                }
            ]
        }
    ]
    chart_ocr = {
        "accepted_tokens": [
            {
                **token.to_dict(),
                "kind": "chord",
                "text_norm": "Bb",
            }
        ],
        "unassigned_tokens": [],
    }
    scan_regions = [
        {
            "source": "cell_ocr_targeted",
            "region": "root",
            "row_index": 1,
            "col_index": 1,
            "measure_index": 1,
            "bbox": [20.0, 40.0, 100.0, 90.0],
        }
    ]

    overlay = render_chord_chart_ocr_debug_overlay(
        image=image,
        pages=pages,
        chart_ocr=chart_ocr,
        ocr_tokens=[token],
        ocr_rejects=[],
        scan_regions=scan_regions,
    )

    assert overlay.shape == image.shape
    assert tuple(overlay[89, 100]) == SCAN_ROOT_COLOUR
    assert np.any(
        np.all(
            overlay[48:74, 42:90] == np.array(OCR_ACCEPTED_COLOUR, dtype=np.uint8),
            axis=2,
        )
    )
    assert tuple(overlay[72, 88]) == CHORD_COLOUR
    assert not np.all(overlay == 255)
