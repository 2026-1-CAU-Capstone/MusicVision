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
    }
    assert "musicxml_measure_number" not in chord_result["pages"][0]["systems"][0][
        "measures"
    ][0]
