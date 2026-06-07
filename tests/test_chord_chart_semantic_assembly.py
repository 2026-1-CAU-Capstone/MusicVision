from __future__ import annotations

import cv2
import numpy as np

from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.semantic_assembly import assemble_semantic_chord_tokens


def test_semantic_assembly_combines_root_accidental_and_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("B", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("b", (28.0, 8.0, 40.0, 24.0), region="root_accidental"),
            _token("6", (38.0, 24.0, 55.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Bb6"]
    assert result.tokens[0].bbox == (10.0, 8.0, 55.0, 42.0)
    assert result.diagnostics[0]["status"] == "accepted"


def test_semantic_assembly_uses_first_root_letter_only() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("Ba", (10.0, 10.0, 34.0, 40.0), region="root"),
            _token("b", (28.0, 8.0, 40.0, 24.0), region="root_accidental"),
            _token("7", (38.0, 24.0, 55.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Bb7"]


def test_semantic_assembly_combines_minor_suffix_fragment() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("F", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("-7", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Fm7"]


def test_semantic_assembly_repairs_numeric_flat_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("67", (10.0, 10.0, 34.0, 40.0), region="root"),
            _token("769", (32.0, 24.0, 72.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["G7b9"]


def test_semantic_assembly_repairs_numeric_flat_nine_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("G", (10.0, 10.0, 34.0, 40.0), region="root"),
            _token("719", (32.0, 24.0, 72.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["G7b9"]


def test_semantic_assembly_repairs_numeric_sharp_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("F7", (10.0, 10.0, 34.0, 40.0), region="root"),
            _token("745", (32.0, 24.0, 72.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["F7#5"]


def test_semantic_assembly_repairs_split_numeric_flat_thirteen_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("D", (10.0, 10.0, 34.0, 40.0), region="root"),
            _token("7113", (32.0, 24.0, 86.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["D7b13"]


def test_semantic_assembly_combines_split_seventh_and_sharp_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("F", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("7", (34.0, 24.0, 52.0, 42.0), region="suffix_lower_right"),
            _token("#5", (50.0, 24.0, 82.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["F7#5"]
    suffix_fragments = [
        fragment
        for fragment in result.diagnostics[0]["fragments"]
        if fragment["role"] == "suffix"
    ]
    assert [fragment["text"] for fragment in suffix_fragments] == ["7", "#5"]


def test_semantic_assembly_uses_root_anchor_local_regions_for_second_flat_chord() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("G", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("-7", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
            _token("G", (120.0, 10.0, 140.0, 40.0), region="root"),
            _token("#b", (138.0, 8.0, 150.0, 24.0), region="root_accidental"),
            _token("7", (146.0, 24.0, 170.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Gm7", "Gb7"]


def test_semantic_assembly_ignores_full_measure_wide_regions() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("F", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("CA", (12.0, 8.0, 42.0, 42.0), region="root_wide"),
            _token("-7", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
            _token("E", (120.0, 10.0, 140.0, 40.0), region="root_wide"),
            _token("C7", (146.0, 24.0, 170.0, 42.0), region="suffix_wide"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Fm7"]


def test_semantic_assembly_prefers_precise_suffix_over_wide_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("A", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("Ao7", (8.0, 18.0, 70.0, 48.0), region="suffix_wide"),
            _token("\u00f87", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Am7b5"]


def test_semantic_assembly_rejects_nearby_invalid_numeric_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("F", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("1", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert result.tokens == []
    assert result.diagnostics[0]["reason"] == "nearby suffix OCR was invalid"


def test_semantic_assembly_ignores_root_overlap_suffix_body() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("B6", (10.0, 10.0, 34.0, 40.0), region="root"),
            _token("b", (28.0, 8.0, 40.0, 24.0), region="root_accidental"),
            _token("6", (38.0, 24.0, 55.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["Bb6"]


def test_semantic_assembly_collapses_duplicate_seventh_suffix() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("C", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("77", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
        ]
    )

    assert [token.text for token in result.tokens] == ["C7"]


def test_semantic_assembly_uses_visual_dash_for_minor_seventh() -> None:
    image = np.full((80, 80, 3), 255, dtype=np.uint8)
    image[34:37, 34:47] = 0
    result = assemble_semantic_chord_tokens(
        [
            _token("F", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("77", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["Fm7"]


def test_semantic_assembly_uses_visual_dash_for_minor_sixth() -> None:
    image = np.full((80, 90, 3), 255, dtype=np.uint8)
    image[34:37, 34:47] = 0
    result = assemble_semantic_chord_tokens(
        [
            _token("G", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("76", (34.0, 24.0, 66.0, 42.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["Gm6"]


def test_semantic_assembly_uses_visual_half_diminished_symbol() -> None:
    image = np.full((90, 90, 3), 255, dtype=np.uint8)
    cv2.circle(image, (42, 36), 12, (0, 0, 0), 2)
    cv2.line(image, (34, 50), (50, 22), (0, 0, 0), 2)
    result = assemble_semantic_chord_tokens(
        [
            _token("A", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("07", (30.0, 18.0, 66.0, 50.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["Am7b5"]


def test_semantic_assembly_uses_visual_diminished_symbol() -> None:
    image = np.full((90, 90, 3), 255, dtype=np.uint8)
    cv2.circle(image, (42, 36), 12, (0, 0, 0), 2)
    result = assemble_semantic_chord_tokens(
        [
            _token("E", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("07", (30.0, 18.0, 66.0, 50.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["Edim7"]


def test_semantic_assembly_uses_visual_triangle_for_major_seventh() -> None:
    image = np.full((90, 90, 3), 255, dtype=np.uint8)
    points = np.array([[34, 42], [45, 20], [56, 42]], dtype=np.int32)
    cv2.polylines(image, [points], isClosed=True, color=(0, 0, 0), thickness=2)
    result = assemble_semantic_chord_tokens(
        [
            _token("B", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("47", (30.0, 18.0, 64.0, 48.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["Bmaj7"]


def test_semantic_assembly_uses_first_letter_root_with_visual_triangle() -> None:
    image = np.full((90, 90, 3), 255, dtype=np.uint8)
    points = np.array([[34, 42], [45, 20], [56, 42]], dtype=np.int32)
    cv2.polylines(image, [points], isClosed=True, color=(0, 0, 0), thickness=2)
    result = assemble_semantic_chord_tokens(
        [
            _token("Gl", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("07", (30.0, 18.0, 64.0, 48.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["Gmaj7"]


def test_semantic_assembly_does_not_treat_plain_seventh_as_triangle() -> None:
    image = np.full((90, 90, 3), 255, dtype=np.uint8)
    points = np.array([[34, 42], [45, 20], [56, 42]], dtype=np.int32)
    cv2.polylines(image, [points], isClosed=True, color=(0, 0, 0), thickness=2)
    result = assemble_semantic_chord_tokens(
        [
            _token("B", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("7", (30.0, 18.0, 64.0, 48.0), region="suffix_lower_right"),
        ],
        image=image,
    )

    assert [token.text for token in result.tokens] == ["B7"]


def test_semantic_assembly_skips_repeat_priority_measures() -> None:
    result = assemble_semantic_chord_tokens(
        [
            _token("C", (10.0, 10.0, 30.0, 40.0), region="root"),
            _token("7", (34.0, 24.0, 58.0, 42.0), region="suffix_lower_right"),
        ],
        skip_measure_indices={1},
    )

    assert result.tokens == []
    assert result.diagnostics[0]["reason"] == "repeat_symbol_priority"


def _token(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    region: str,
) -> OCRToken:
    return OCRToken(
        text=text,
        bbox=bbox,
        confidence=0.9,
        source="cell_ocr_semantic",
        row_index=1,
        col_index=1,
        measure_index=1,
        region=region,
    )
