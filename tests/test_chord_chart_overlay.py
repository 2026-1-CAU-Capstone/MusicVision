from __future__ import annotations

import numpy as np

from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.overlay import (
    CHORD_COLOUR,
    OCR_REJECTED_COLOUR,
    SCAN_ACCIDENTAL_COLOUR,
    SCAN_SUFFIX_COLOUR,
    render_chord_chart_ocr_debug_overlay,
)


def test_chord_chart_ocr_debug_overlay_draws_semantic_region_value_labels() -> None:
    image = np.full((150, 240, 3), 255, dtype=np.uint8)
    unused_suffix_token = OCRToken(
        "-7",
        (12.0, 120.0, 32.0, 136.0),
        0.82,
        "cell_ocr_targeted",
        row_index=1,
        col_index=1,
        measure_index=1,
        region="suffix_lower_right",
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
                                    "bbox": [64.0, 70.0, 104.0, 92.0],
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
        "strategy": {
            "semantic_assembly": [
                {
                    "measure_index": 1,
                    "status": "accepted",
                    "text": "Bb6",
                    "fragments": [
                        {
                            "role": "root",
                            "text": "B",
                            "bbox": [64.0, 70.0, 84.0, 92.0],
                            "confidence": 0.95,
                        },
                        {
                            "role": "accidental",
                            "text": "b",
                            "bbox": [120.0, 56.0, 135.0, 78.0],
                            "confidence": 0.91,
                        },
                        {
                            "role": "suffix",
                            "text": "A",
                            "bbox": [40.0, 100.0, 60.0, 118.0],
                            "confidence": 0.99,
                        },
                        {
                            "role": "suffix",
                            "text": "-7",
                            "bbox": [86.0, 96.0, 118.0, 112.0],
                            "confidence": 0.82,
                        },
                        {
                            "role": "suffix",
                            "text": "-7",
                            "bbox": [88.0, 98.0, 116.0, 113.0],
                            "confidence": 0.93,
                        },
                    ],
                },
                {
                    "measure_index": 1,
                    "status": "rejected",
                    "text": "Bb",
                    "fragments": [
                        {
                            "role": "accidental",
                            "text": "Pb",
                            "bbox": [168.0, 52.0, 188.0, 84.0],
                            "confidence": 0.4,
                        }
                    ],
                },
            ]
        }
    }
    scan_regions = [
        {
            "source": "cell_ocr_targeted",
            "region": "suffix_lower_right",
            "row_index": 1,
            "col_index": 1,
            "measure_index": 1,
            "bbox": [82.0, 92.0, 122.0, 116.0],
        },
        {
            "source": "cell_ocr_targeted",
            "region": "root_accidental",
            "row_index": 1,
            "col_index": 1,
            "measure_index": 1,
            "bbox": [116.0, 52.0, 139.0, 82.0],
        }
    ]

    overlay = render_chord_chart_ocr_debug_overlay(
        image=image,
        pages=pages,
        chart_ocr=chart_ocr,
        ocr_tokens=[unused_suffix_token],
        ocr_rejects=[
            {
                "text": "noise",
                "bbox": [12.0, 120.0, 32.0, 136.0],
                "confidence": 0.01,
            }
        ],
        scan_regions=scan_regions,
    )

    assert overlay.shape == image.shape
    assert tuple(overlay[113, 116]) == SCAN_SUFFIX_COLOUR
    assert tuple(overlay[56, 135]) == SCAN_ACCIDENTAL_COLOUR
    assert tuple(overlay[56, 135]) != CHORD_COLOUR
    assert tuple(overlay[56, 64]) == CHORD_COLOUR
    assert np.any(np.all(overlay[66:96, 8:64] == CHORD_COLOUR, axis=2))
    assert np.any(np.all(overlay[110:140, 84:122] == SCAN_SUFFIX_COLOUR, axis=2))
    assert np.any(
        np.all(overlay[52:88, 136:176] == SCAN_ACCIDENTAL_COLOUR, axis=2)
    )
    assert not np.any(np.all(overlay[100:120, 38:62] == SCAN_SUFFIX_COLOUR, axis=2))
    assert not np.any(np.all(overlay == OCR_REJECTED_COLOUR, axis=2))
    assert not np.all(overlay == 255)
