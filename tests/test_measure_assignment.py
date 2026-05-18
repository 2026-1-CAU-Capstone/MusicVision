from __future__ import annotations

import numpy as np
import pytest

from pipeline.chords.measure_assignment import assign_chords_to_measures
from pipeline.chords.models import ChordToken


def test_measure_assignment_prefers_homr_geometry() -> None:
    geometry = {
        "coordinate_space": "homr_processed_image",
        "image": {"width": 420, "height": 220},
        "systems": [
            {
                "index": 1,
                "bbox": [20, 70, 400, 150],
                "staffs": [{"index": 1, "bbox": [20, 70, 400, 150]}],
            }
        ],
        "barlines": [
            {"bbox": [30, 70, 34, 150], "center": [32, 110]},
            {"bbox": [130, 70, 134, 150], "center": [132, 110]},
            {"bbox": [230, 70, 234, 150], "center": [232, 110]},
            {"bbox": [330, 70, 334, 150], "center": [332, 110]},
        ],
    }
    tokens = [
        ChordToken("Dm7", "Dm7", (60, 30, 90, 50)),
        ChordToken("G7", "G7", (160, 30, 185, 50)),
        ChordToken("Cmaj7", "Cmaj7", (265, 30, 315, 50)),
    ]

    result = assign_chords_to_measures(
        tokens=tokens,
        geometry=geometry,
        image=np.zeros((220, 420, 3), dtype=np.uint8),
        source_path="homr_processed.png",
    )

    page = result["pages"][0]
    measures = page["systems"][0]["measures"]

    assert page["assignment_source"] == "homr_geometry"
    assert [measure["bbox"] for measure in measures] == [
        [32.0, 70.0, 132.0, 150.0],
        [132.0, 70.0, 232.0, 150.0],
        [232.0, 70.0, 332.0, 150.0],
    ]
    assert [measure["chords"][0]["text_norm"] for measure in measures] == [
        "Dm7",
        "G7",
        "Cmaj7",
    ]
    assert [measure["chords"][0]["beat"] for measure in measures] == [2, 2, 3]


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {
            "coordinate_space": "homr_processed_image",
            "image": {"width": 260, "height": 180},
            "systems": [{"index": 1, "bbox": [10, 60, 250, 130], "staffs": []}],
            "barlines": [{"bbox": [20, 60, 24, 130], "center": [22, 95]}],
        },
    ],
)
def test_measure_assignment_falls_back_when_homr_geometry_is_missing_or_insufficient(
    geometry: dict | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"value": False}

    def fake_detect_barlines_cv(_image: np.ndarray):
        called["value"] = True
        return (
            [(20.0, 0.0, 180.0), (120.0, 0.0, 180.0), (220.0, 0.0, 180.0)],
            np.zeros((180, 260), dtype=np.uint8),
        )

    monkeypatch.setattr(
        "pipeline.chords.measure_assignment.detect_barlines_cv",
        fake_detect_barlines_cv,
    )

    result = assign_chords_to_measures(
        tokens=[
            ChordToken("Dm7", "Dm7", (40, 20, 70, 40)),
            ChordToken("G7", "G7", (150, 20, 175, 40)),
        ],
        geometry=geometry,
        image=np.zeros((180, 260, 3), dtype=np.uint8),
        source_path="homr_processed.png",
    )

    page = result["pages"][0]
    measures = page["systems"][0]["measures"]

    assert called["value"] is True
    assert page["assignment_source"] == "cv_fallback"
    assert [measure["chords"][0]["text_norm"] for measure in measures] == ["Dm7", "G7"]
