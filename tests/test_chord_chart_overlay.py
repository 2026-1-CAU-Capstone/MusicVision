from __future__ import annotations

import numpy as np

from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.overlay import (
    CHORD_COLOUR,
    OCR_REJECTED_COLOUR,
    SCAN_ROOT_COLOUR,
    SCAN_ACCIDENTAL_COLOUR,
    SCAN_SUFFIX_COLOUR,
    render_chord_chart_ocr_debug_overlay,
    render_chord_chart_root_ocr_bbox_overlay,
    render_chord_chart_scan_boundary_overlay,
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


def test_chord_chart_scan_boundary_overlay_draws_all_semantic_scan_boxes() -> None:
    image = np.full((300, 520, 3), 255, dtype=np.uint8)
    pages = [
        {
            "systems": [
                {
                    "measures": [
                        {
                            "index": 1,
                            "bbox": [220.0, 120.0, 440.0, 240.0],
                            "chords": [],
                            "symbols": [],
                            "navigation": [],
                        }
                    ]
                }
            ]
        }
    ]
    scan_regions = [
        {
            "source": "cell_ocr_root_anchor",
            "region": "root",
            "row_index": 1,
            "col_index": 1,
            "measure_index": 1,
            "anchor_index": 2,
            "bbox": [242.0, 154.0, 292.0, 212.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "root_accidental",
            "row_index": 1,
            "col_index": 1,
            "measure_index": 1,
            "anchor_index": 2,
            "bbox": [286.0, 150.0, 316.0, 182.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "suffix_lower_right",
            "row_index": 1,
            "col_index": 1,
            "measure_index": 1,
            "anchor_index": 2,
            "bbox": [290.0, 186.0, 354.0, 224.0],
        },
    ]

    overlay = render_chord_chart_scan_boundary_overlay(
        image=image,
        pages=pages,
        scan_regions=scan_regions,
    )

    assert overlay.shape == image.shape
    assert tuple(overlay[154, 242]) == SCAN_ROOT_COLOUR
    assert tuple(overlay[150, 316]) == SCAN_ACCIDENTAL_COLOUR
    assert tuple(overlay[224, 354]) == SCAN_SUFFIX_COLOUR
    assert np.any(np.all(overlay[136:156, 242:390] == SCAN_ROOT_COLOUR, axis=2))
    assert np.any(np.all(overlay[166:196, 316:452] == SCAN_ACCIDENTAL_COLOUR, axis=2))
    assert np.any(np.all(overlay[224:250, 290:460] == SCAN_SUFFIX_COLOUR, axis=2))


def test_chord_chart_root_ocr_bbox_overlay_draws_detected_root_boxes() -> None:
    image = np.full((180, 300, 3), 255, dtype=np.uint8)
    pages = [
        {
            "systems": [
                {
                    "measures": [
                        {
                            "index": 1,
                            "bbox": [30.0, 70.0, 260.0, 150.0],
                            "chords": [],
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
                    "text": "D7",
                    "fragments": [
                        {
                            "role": "root",
                            "text": "D",
                            "bbox": [64.0, 88.0, 104.0, 138.0],
                        },
                    ],
                },
                {
                    "measure_index": 1,
                    "status": "rejected",
                    "text": "G",
                    "fragments": [
                        {
                            "role": "root",
                            "text": "G",
                            "bbox": [164.0, 88.0, 204.0, 138.0],
                        },
                    ],
                },
            ]
        }
    }

    overlay = render_chord_chart_root_ocr_bbox_overlay(
        image=image,
        pages=pages,
        chart_ocr=chart_ocr,
    )

    assert tuple(overlay[88, 64]) == SCAN_ROOT_COLOUR
    assert tuple(overlay[88, 164]) == OCR_REJECTED_COLOUR
    assert tuple(overlay[138, 104]) == SCAN_ROOT_COLOUR
    assert tuple(overlay[138, 204]) == OCR_REJECTED_COLOUR
    assert np.any(np.all(overlay[64:88, 64:120] == SCAN_ROOT_COLOUR, axis=2))


def test_chord_chart_scan_boundary_overlay_draws_only_accepted_anchor_boxes() -> None:
    image = np.full((280, 460, 3), 255, dtype=np.uint8)
    pages = [
        {
            "systems": [
                {
                    "measures": [
                        {
                            "index": 1,
                            "bbox": [32.0, 96.0, 428.0, 228.0],
                            "chords": [],
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
                    "text": "Bb7",
                    "fragments": [
                        {
                            "role": "root",
                            "text": "B",
                            "debug": {
                                "root_anchor": {
                                    "measure_index": 1,
                                    "anchor_index": 2,
                                }
                            },
                        }
                    ],
                }
            ]
        }
    }
    scan_regions = [
        {
            "source": "cell_ocr_semantic",
            "region": "suffix_lower_right",
            "measure_index": 1,
            "bbox": [108.0, 146.0, 206.0, 196.0],
        },
        {
            "source": "cell_ocr_semantic",
            "region": "root_accidental",
            "measure_index": 1,
            "bbox": [94.0, 110.0, 144.0, 156.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "root",
            "measure_index": 1,
            "anchor_index": 1,
            "bbox": [58.0, 116.0, 108.0, 208.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "root_accidental",
            "measure_index": 1,
            "anchor_index": 1,
            "bbox": [98.0, 112.0, 134.0, 156.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "suffix_lower_right",
            "measure_index": 1,
            "anchor_index": 1,
            "bbox": [100.0, 150.0, 188.0, 208.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "root",
            "measure_index": 1,
            "anchor_index": 2,
            "bbox": [238.0, 116.0, 288.0, 208.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "root_accidental",
            "measure_index": 1,
            "anchor_index": 2,
            "bbox": [278.0, 112.0, 314.0, 156.0],
        },
        {
            "source": "cell_ocr_root_anchor",
            "region": "suffix_lower_right",
            "measure_index": 1,
            "anchor_index": 2,
            "bbox": [280.0, 150.0, 368.0, 208.0],
        },
    ]

    overlay = render_chord_chart_scan_boundary_overlay(
        image=image,
        pages=pages,
        scan_regions=scan_regions,
        chart_ocr=chart_ocr,
    )

    assert tuple(overlay[116, 238]) == SCAN_ROOT_COLOUR
    assert tuple(overlay[136, 314]) == SCAN_ACCIDENTAL_COLOUR
    assert tuple(overlay[208, 368]) == SCAN_SUFFIX_COLOUR
    assert tuple(overlay[136, 134]) == (255, 255, 255)
    assert tuple(overlay[208, 188]) == (255, 255, 255)
    assert tuple(overlay[156, 144]) == (255, 255, 255)
    assert tuple(overlay[196, 206]) == (255, 255, 255)
