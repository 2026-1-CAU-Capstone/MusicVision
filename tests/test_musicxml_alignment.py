from __future__ import annotations

from pathlib import Path

from pipeline.musicxml_alignment import annotate_measure_alignment


def test_measure_alignment_annotates_visual_measures_when_counts_match(
    tmp_path: Path,
) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    musicxml_path.write_text(
        """
        <score-partwise>
          <part id="P1">
            <measure number="1"/>
            <measure number="2"/>
          </part>
        </score-partwise>
        """,
        encoding="utf-8",
    )
    chord_result = {
        "pages": [
            {
                "systems": [
                    {
                        "measures": [
                            {"index": 1},
                            {"index": 2},
                        ]
                    }
                ]
            }
        ]
    }

    alignment = annotate_measure_alignment(
        chord_result=chord_result,
        musicxml_path=musicxml_path,
    )

    assert alignment == {
        "status": "aligned",
        "musicxml_measure_count": 2,
        "visual_measure_count": 2,
        "musicxml_system_count": 1,
        "visual_system_count": 1,
        "aligned_system_count": 1,
        "mismatched_system_count": 0,
        "system_alignment": [
            {
                "visual_system_index": 1,
                "musicxml_system_index": 1,
                "status": "aligned",
                "musicxml_measure_count": 2,
                "visual_measure_count": 2,
            }
        ],
    }
    assert [
        measure["musicxml_measure_number"]
        for measure in chord_result["pages"][0]["systems"][0]["measures"]
    ] == ["1", "2"]


def test_measure_alignment_reports_mismatch_without_guessing_correspondence(
    tmp_path: Path,
) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    musicxml_path.write_text(
        """
        <score-partwise>
          <part id="P1">
            <measure number="1"/>
            <measure number="2"/>
          </part>
        </score-partwise>
        """,
        encoding="utf-8",
    )
    chord_result = {
        "pages": [
            {
                "systems": [
                    {
                        "measures": [
                            {"index": 1},
                        ]
                    }
                ]
            }
        ]
    }

    alignment = annotate_measure_alignment(
        chord_result=chord_result,
        musicxml_path=musicxml_path,
    )

    assert alignment == {
        "status": "mismatch",
        "musicxml_measure_count": 2,
        "visual_measure_count": 1,
        "musicxml_system_count": 1,
        "visual_system_count": 1,
        "aligned_system_count": 0,
        "mismatched_system_count": 1,
        "system_alignment": [
            {
                "visual_system_index": 1,
                "musicxml_system_index": 1,
                "status": "mismatch",
                "musicxml_measure_count": 2,
                "visual_measure_count": 1,
            }
        ],
    }
    assert "musicxml_measure_number" not in chord_result["pages"][0]["systems"][0][
        "measures"
    ][0]


def test_measure_alignment_partially_annotates_matching_systems(
    tmp_path: Path,
) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    musicxml_path.write_text(
        """
        <score-partwise>
          <part id="P1">
            <measure number="1"/>
            <measure number="2"/>
            <measure number="3"><print new-system="yes"/></measure>
            <measure number="4"/>
            <measure number="5"><print new-system="yes"/></measure>
            <measure number="6"/>
          </part>
        </score-partwise>
        """,
        encoding="utf-8",
    )
    chord_result = {
        "pages": [
            {
                "systems": [
                    {
                        "index": 1,
                        "measures": [
                            {"index": 1},
                            {"index": 2},
                        ],
                    },
                    {
                        "index": 2,
                        "measures": [
                            {"index": 3},
                        ],
                    },
                    {
                        "index": 3,
                        "measures": [
                            {"index": 4},
                            {"index": 5},
                        ],
                    },
                ]
            }
        ]
    }

    alignment = annotate_measure_alignment(
        chord_result=chord_result,
        musicxml_path=musicxml_path,
    )

    assert alignment == {
        "status": "partial",
        "musicxml_measure_count": 6,
        "visual_measure_count": 5,
        "musicxml_system_count": 3,
        "visual_system_count": 3,
        "aligned_system_count": 2,
        "mismatched_system_count": 1,
        "system_alignment": [
            {
                "visual_system_index": 1,
                "musicxml_system_index": 1,
                "status": "aligned",
                "musicxml_measure_count": 2,
                "visual_measure_count": 2,
            },
            {
                "visual_system_index": 2,
                "musicxml_system_index": 2,
                "status": "mismatch",
                "musicxml_measure_count": 2,
                "visual_measure_count": 1,
            },
            {
                "visual_system_index": 3,
                "musicxml_system_index": 3,
                "status": "aligned",
                "musicxml_measure_count": 2,
                "visual_measure_count": 2,
            },
        ],
    }
    systems = chord_result["pages"][0]["systems"]
    assert [measure["musicxml_measure_number"] for measure in systems[0]["measures"]] == [
        "1",
        "2",
    ]
    assert "musicxml_measure_number" not in systems[1]["measures"][0]
    assert [measure["musicxml_measure_number"] for measure in systems[2]["measures"]] == [
        "5",
        "6",
    ]
