from __future__ import annotations

from pipeline.chord_charts.public_payload import build_public_chord_chart_payload


def test_public_chord_chart_payload_keeps_final_music_without_ocr_debug() -> None:
    full_payload = {
        "job_id": "chart-job",
        "source_file": "chart.png",
        "source_type": "chord_chart",
        "title": "Demo",
        "composer": "Composer",
        "style": "Swing",
        "time_signature": {"numerator": 4, "denominator": 4},
        "beats_per_bar": 4,
        "flow": {
            "sections": [
                {"section": "A", "start_measure_index": 1, "end_measure_index": 2}
            ],
            "repeat_groups": [
                {"start_measure_index": 1, "end_measure_index": 2, "section": "A"}
            ],
            "endings": [
                {
                    "number": 1,
                    "start_measure_index": 1,
                    "end_measure_index": 1,
                    "section": "A",
                }
            ],
            "navigation": [
                {
                    "type": "fine",
                    "text_raw": "Fine",
                    "measure_index": 2,
                    "section": "A",
                    "bbox": [1, 2, 3, 4],
                }
            ],
        },
        "chart_ocr": {
            "backend": "easyocr",
            "accepted_tokens": [{"text": "C7"}],
        },
        "pages": [
            {
                "systems": [
                    {
                        "measures": [
                            {
                                "index": 1,
                                "section": "A",
                                "bbox": [0, 0, 100, 100],
                                "chords": [
                                    {
                                        "text_raw": "Cz",
                                        "text_norm": "C7",
                                        "beat": 1,
                                        "components": {"root": "C"},
                                        "bbox": [10, 10, 30, 30],
                                    }
                                ],
                            },
                            {
                                "index": 2,
                                "section": "A",
                                "chords": [],
                                "resolved_chords": [
                                    {
                                        "text_norm": "C7",
                                        "beat": 1,
                                        "derived_from_measure_index": 1,
                                    }
                                ],
                            },
                        ]
                    }
                ]
            }
        ],
        "warnings": [],
    }

    public_payload = build_public_chord_chart_payload(full_payload)

    assert public_payload == {
        "job_id": "chart-job",
        "source_file": "chart.png",
        "source_type": "chord_chart",
        "title": "Demo",
        "composer": "Composer",
        "style": "Swing",
        "time_signature": {"numerator": 4, "denominator": 4},
        "beats_per_bar": 4,
        "measure_count": 2,
        "chords": [
            {
                "kind": "chord",
                "text": "C7",
                "measure_index": 1,
                "beat": 1,
                "section": "A",
                "source": "direct",
            },
            {
                "kind": "chord",
                "text": "%",
                "measure_index": 2,
                "beat": 1,
                "section": "A",
                "source": "repeat_previous_measure",
                "derived_from_measure_index": 1,
            },
        ],
        "flow": {
            "sections": [
                {"section": "A", "start_measure_index": 1, "end_measure_index": 2}
            ],
            "repeat_groups": [
                {"start_measure_index": 1, "end_measure_index": 2, "section": "A"}
            ],
            "endings": [
                {
                    "number": 1,
                    "start_measure_index": 1,
                    "end_measure_index": 1,
                    "section": "A",
                }
            ],
            "navigation": [
                {"type": "fine", "measure_index": 2, "section": "A", "text": "Fine"}
            ],
        },
        "warnings": [],
    }
    assert "chart_ocr" not in public_payload
    assert "pages" not in public_payload
