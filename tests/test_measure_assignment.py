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


def test_measure_assignment_keeps_leading_system_interval_as_first_measure() -> None:
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
            {"bbox": [120, 70, 124, 150], "center": [122, 110]},
            {"bbox": [220, 70, 224, 150], "center": [222, 110]},
            {"bbox": [320, 70, 324, 150], "center": [322, 110]},
        ],
    }

    result = assign_chords_to_measures(
        tokens=[
            ChordToken("Dm7", "Dm7", (50, 30, 80, 50)),
            ChordToken("G7", "G7", (150, 30, 175, 50)),
        ],
        geometry=geometry,
        image=np.zeros((220, 420, 3), dtype=np.uint8),
        source_path="homr_processed.png",
    )

    measures = result["pages"][0]["systems"][0]["measures"]

    assert [measure["bbox"] for measure in measures] == [
        [20.0, 70.0, 122.0, 150.0],
        [122.0, 70.0, 222.0, 150.0],
        [222.0, 70.0, 322.0, 150.0],
    ]
    assert [measure["chords"][0]["text_norm"] for measure in measures[:2]] == [
        "Dm7",
        "G7",
    ]


def test_measure_assignment_recovers_a_missing_barline_inside_an_overwide_interval() -> None:
    image = np.full((220, 600, 3), 255, dtype=np.uint8)
    for x in (120, 220, 320, 420, 520):
        image[70:151, x : x + 3] = 0

    geometry = {
        "coordinate_space": "homr_processed_image",
        "image": {"width": 600, "height": 220},
        "systems": [
            {
                "index": 1,
                "bbox": [20, 70, 560, 150],
                "staffs": [{"index": 1, "bbox": [20, 70, 560, 150]}],
            }
        ],
        "barlines": [
            {"bbox": [120, 70, 123, 150], "center": [121.5, 110]},
            {"bbox": [320, 70, 323, 150], "center": [321.5, 110]},
            {"bbox": [420, 70, 423, 150], "center": [421.5, 110]},
            {"bbox": [520, 70, 523, 150], "center": [521.5, 110]},
        ],
    }

    result = assign_chords_to_measures(
        tokens=[
            ChordToken("Dm7", "Dm7", (145, 30, 175, 50)),
            ChordToken("G7", "G7", (225, 30, 245, 50)),
        ],
        geometry=geometry,
        image=image,
        source_path="homr_processed.png",
    )

    measures = result["pages"][0]["systems"][0]["measures"]

    assert [measure["bbox"] for measure in measures] == [
        [20.0, 70.0, 121.5, 150.0],
        [121.5, 70.0, 221.0, 150.0],
        [221.0, 70.0, 321.5, 150.0],
        [321.5, 70.0, 421.5, 150.0],
        [421.5, 70.0, 521.5, 150.0],
    ]
    assert measures[2]["chords"][0]["text_norm"] == "G7"
    assert measures[2]["chords"][0]["beat"] == 1


def test_measure_assignment_uses_leading_boundary_when_detecting_overwide_intervals() -> None:
    image = np.full((220, 1920, 3), 255, dtype=np.uint8)
    for x in (543, 1017, 1490, 1865):
        image[70:151, x : x + 3] = 0

    geometry = {
        "coordinate_space": "homr_processed_image",
        "image": {"width": 1920, "height": 220},
        "systems": [
            {
                "index": 1,
                "bbox": [30, 70, 1870, 150],
                "staffs": [{"index": 1, "bbox": [30, 70, 1870, 150]}],
            }
        ],
        "barlines": [
            {"bbox": [543, 70, 546, 150], "center": [544.5, 110]},
            {"bbox": [1490, 70, 1493, 150], "center": [1491.5, 110]},
            {"bbox": [1865, 70, 1868, 150], "center": [1866.5, 110]},
        ],
    }

    result = assign_chords_to_measures(
        tokens=[
            ChordToken("Gmaj7", "Gmaj7", (600, 30, 700, 50)),
            ChordToken("Ebmaj7", "Ebmaj7", (1100, 30, 1230, 50)),
        ],
        geometry=geometry,
        image=image,
        source_path="homr_processed.png",
    )

    measures = result["pages"][0]["systems"][0]["measures"]

    assert [measure["bbox"] for measure in measures] == [
        [30.0, 70.0, 544.5, 150.0],
        [544.5, 70.0, 1018.0, 150.0],
        [1018.0, 70.0, 1491.5, 150.0],
        [1491.5, 70.0, 1866.5, 150.0],
    ]
    assert [measure["chords"][0]["text_norm"] for measure in measures[1:3]] == [
        "Gmaj7",
        "Ebmaj7",
    ]


def test_measure_assignment_can_use_expected_system_count_to_inspect_suspicious_gap() -> None:
    image = np.full((220, 1500, 3), 255, dtype=np.uint8)
    for x in (420, 730, 1040, 1470):
        image[70:151, x : x + 3] = 0

    geometry = {
        "coordinate_space": "homr_processed_image",
        "image": {"width": 1500, "height": 220},
        "systems": [
            {
                "index": 1,
                "bbox": [20, 70, 1480, 150],
                "staffs": [{"index": 1, "bbox": [20, 70, 1480, 150]}],
            }
        ],
        "barlines": [
            {"bbox": [420, 70, 423, 150], "center": [421.5, 110]},
            {"bbox": [1040, 70, 1043, 150], "center": [1041.5, 110]},
            {"bbox": [1470, 70, 1473, 150], "center": [1471.5, 110]},
        ],
    }

    without_expected_count = assign_chords_to_measures(
        tokens=[],
        geometry=geometry,
        image=image,
        source_path="homr_processed.png",
    )
    with_expected_count = assign_chords_to_measures(
        tokens=[],
        geometry=geometry,
        image=image,
        source_path="homr_processed.png",
        expected_measure_counts_by_system=[4],
    )

    assert len(without_expected_count["pages"][0]["systems"][0]["measures"]) == 3
    assert [
        measure["bbox"]
        for measure in with_expected_count["pages"][0]["systems"][0]["measures"]
    ] == [
        [20.0, 70.0, 421.5, 150.0],
        [421.5, 70.0, 731.0, 150.0],
        [731.0, 70.0, 1041.5, 150.0],
        [1041.5, 70.0, 1471.5, 150.0],
    ]


def test_measure_assignment_prefers_token_system_index_when_available() -> None:
    geometry = {
        "coordinate_space": "homr_processed_image",
        "image": {"width": 500, "height": 360},
        "systems": [
            {
                "index": 1,
                "bbox": [20, 70, 480, 130],
                "staffs": [{"index": 1, "bbox": [20, 70, 480, 130]}],
            },
            {
                "index": 2,
                "bbox": [20, 190, 480, 250],
                "staffs": [{"index": 1, "bbox": [20, 190, 480, 250]}],
            },
        ],
        "barlines": [
            {"bbox": [30, 70, 34, 130], "center": [32, 100]},
            {"bbox": [230, 70, 234, 130], "center": [232, 100]},
            {"bbox": [430, 70, 434, 130], "center": [432, 100]},
            {"bbox": [30, 190, 34, 250], "center": [32, 220]},
            {"bbox": [230, 190, 234, 250], "center": [232, 220]},
            {"bbox": [430, 190, 434, 250], "center": [432, 220]},
        ],
    }
    token = ChordToken(
        "Bb-7",
        "Bb-7",
        (70, 125, 120, 145),
        confidence=0.7,
        system_index=2,
    )

    result = assign_chords_to_measures(
        tokens=[token],
        geometry=geometry,
        image=np.zeros((360, 500, 3), dtype=np.uint8),
        source_path="homr_processed.png",
    )

    systems = result["pages"][0]["systems"]
    assert systems[0]["measures"][0]["chords"] == []
    assert systems[1]["measures"][0]["chords"][0]["text_norm"] == "Bb-7"


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
