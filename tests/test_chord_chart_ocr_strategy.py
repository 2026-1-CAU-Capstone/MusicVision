from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.ocr_strategy import (
    plan_multi_chord_chart_cell_ocr,
    plan_selective_chart_cell_ocr,
    root_anchor_hints_from_plan,
)
from pipeline.chord_charts.parser import Boundary, ChartRow


def _rows() -> list[ChartRow]:
    return [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(200, 100, 200, 1),
                Boundary(350, 100, 200, 1),
            ],
        )
    ]


def test_selective_plan_flags_page_row_chord_disagreement() -> None:
    plan = plan_selective_chart_cell_ocr(
        rows=_rows(),
        page_tokens=[OCRToken("G7b9", (75, 115, 140, 160), 0.70, "page_ocr")],
        row_tokens=[
            OCRToken("G7", (75, 115, 125, 160), 0.92, "cell_ocr_row_system")
        ],
    )

    assert plan.measure_indices == [1]
    reasons = plan.diagnostics["selected_measures"][0]["reasons"]
    assert "page_row_disagreement" in reasons
    assert "contained_shorter_longer_chord" in reasons


def test_selective_plan_flags_low_confidence_and_suffix_fragments() -> None:
    plan = plan_selective_chart_cell_ocr(
        rows=_rows(),
        page_tokens=[
            OCRToken("F7", (75, 115, 120, 160), 0.42, "page_ocr"),
            OCRToken("#5", (122, 130, 150, 165), 0.38, "page_ocr"),
        ],
        row_tokens=[],
    )

    assert plan.measure_indices == [1]
    reasons = plan.diagnostics["selected_measures"][0]["reasons"]
    assert "low_confidence_candidate" in reasons
    assert "suffix_fragment_near_candidate" in reasons


def test_selective_plan_ignores_clean_agreement() -> None:
    plan = plan_selective_chart_cell_ocr(
        rows=_rows(),
        page_tokens=[OCRToken("C7", (75, 115, 125, 160), 0.90, "page_ocr")],
        row_tokens=[
            OCRToken("C7", (75, 115, 125, 160), 0.93, "cell_ocr_row_system")
        ],
    )

    assert plan.measure_indices == []


def test_multi_chord_plan_flags_wide_token_with_space() -> None:
    plan = plan_multi_chord_chart_cell_ocr(
        rows=_rows(),
        page_tokens=[OCRToken("Ig- G", (55, 115, 195, 160), 0.50, "page_ocr")],
        row_tokens=[],
    )

    assert plan.measure_indices == [1]
    reasons = plan.diagnostics["selected_measures"][0]["reasons"]
    assert "wide_ocr_token_with_internal_space" in reasons
    hints = root_anchor_hints_from_plan(plan)
    assert [hint["root"] for hint in hints] == ["G", "G"]


def test_multi_chord_plan_flags_right_half_chord_like_fragment() -> None:
    plan = plan_multi_chord_chart_cell_ocr(
        rows=_rows(),
        page_tokens=[
            OCRToken("IF-", (55, 115, 115, 160), 0.95, "page_ocr"),
            OCRToken("Ez", (138, 115, 190, 160), 0.98, "page_ocr"),
        ],
        row_tokens=[],
    )

    assert plan.measure_indices == [1]
    reasons = plan.diagnostics["selected_measures"][0]["reasons"]
    assert "right_half_chord_like_fragment" in reasons
    hints = root_anchor_hints_from_plan(plan)
    assert [hint["root"] for hint in hints] == ["F", "E"]
