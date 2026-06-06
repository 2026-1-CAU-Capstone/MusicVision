from __future__ import annotations

import cv2
import numpy as np

from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.parser import Boundary, ChartRow, parse_chord_chart_image


def test_chord_chart_parser_handles_grid_symbols_and_flow() -> None:
    image = np.full((420, 520, 3), 255, dtype=np.uint8)
    x_positions = [60, 160, 260, 360, 460]
    for y0, y1 in [(100, 190), (250, 340)]:
        for x in x_positions:
            cv2.line(image, (x, y0), (x, y1), (0, 0, 0), 4)

    # Start repeat at row 1, end repeat at row 1.
    for y in (128, 162):
        cv2.circle(image, (82, y), 7, (0, 0, 0), -1)
        cv2.circle(image, (440, y), 7, (0, 0, 0), -1)

    tokens = [
        OCRToken("A", (18, 62, 48, 92), 0.99),
        OCRToken("4/4", (8, 112, 45, 178), 0.99),
        OCRToken("C-7", (78, 116, 130, 150), 0.96),
        OCRToken("%", (198, 122, 225, 152), 0.95),
        OCRToken("G-7", (278, 112, 325, 145), 0.96),
        OCRToken("F", (292, 166, 312, 187), 0.94),
        OCRToken("Fine", (372, 150, 430, 180), 0.93),
        OCRToken("1.", (66, 222, 96, 246), 0.91),
        OCRToken("D.C. al 2nd ending", (305, 345, 490, 378), 0.90),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
    )

    assert payload["source_type"] == "chord_chart"
    assert payload["time_signature"]["numerator"] == 4
    assert payload["pages"][0]["systems"][0]["section"] == "A"

    measures = [
        measure
        for system in payload["pages"][0]["systems"]
        for measure in system["measures"]
    ]
    assert measures[0]["left_boundary"]["kind"] == "start_repeat"
    assert measures[3]["right_boundary"]["kind"] == "end_repeat"
    assert measures[0]["chords"][0]["text_norm"] == "Cm7"
    assert measures[1]["symbols"][0]["type"] == "repeat_previous_measure"
    assert measures[1]["resolved_chords"][0]["text_norm"] == "Cm7"
    assert measures[2]["chords"][0]["text_norm"] == "Gm7/F"
    assert measures[4]["ending"] == {"number": 1}

    assert payload["flow"]["repeat_groups"] == [
        {"start_measure_index": 1, "end_measure_index": 4, "section": "A"}
    ]
    assert payload["flow"]["sections"] == [
        {"section": "A", "start_measure_index": 1, "end_measure_index": 8}
    ]
    assert payload["flow"]["endings"] == [
        {
            "number": 1,
            "start_measure_index": 5,
            "end_measure_index": 8,
            "section": "A",
        }
    ]
    assert payload["flow"]["navigation"][0]["type"] == "fine"
    assert payload["chart_ocr"]["detected_symbols"][-1]["type"] == "dc_al_ending"


def test_chord_chart_parser_deduplicates_navigation_across_ocr_passes() -> None:
    image = np.full((260, 360, 3), 255, dtype=np.uint8)
    rows = [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(310, 100, 200, 1),
            ],
        )
    ]
    tokens = [
        OCRToken("Fine", (200, 202, 275, 230), 0.92, source="page_ocr"),
        OCRToken(
            "Fine",
            (202, 203, 274, 229),
            0.99,
            source="cell_ocr_row_system",
            row_index=1,
            region="row_system",
        ),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
        rows=rows,
    )

    measure = payload["pages"][0]["systems"][0]["measures"][0]
    assert [navigation["type"] for navigation in measure["navigation"]] == ["fine"]
    assert [navigation["type"] for navigation in payload["flow"]["navigation"]] == [
        "fine"
    ]
    assert [
        symbol["type"]
        for symbol in payload["chart_ocr"]["detected_symbols"]
        if symbol["type"] == "fine"
    ] == ["fine"]


def test_chord_chart_parser_recovers_fragmented_quality_and_stacked_bass() -> None:
    image = np.full((300, 430, 3), 255, dtype=np.uint8)
    cv2.line(image, (105, 196), (135, 150), (0, 0, 0), 5)
    rows = [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(200, 100, 200, 1),
                Boundary(380, 100, 200, 1),
            ],
        )
    ]
    tokens = [
        OCRToken("Bp", (74, 116, 122, 180), 0.91, source="cell_ocr"),
        OCRToken("6", (118, 136, 138, 160), 0.92, source="cell_ocr"),
        OCRToken("e", (106, 166, 126, 228), 0.77, source="cell_ocr"),
        OCRToken("A", (224, 118, 274, 176), 0.95, source="cell_ocr"),
        OCRToken("U/", (266, 146, 292, 166), 0.48, source="cell_ocr"),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
        rows=rows,
    )

    measures = payload["pages"][0]["systems"][0]["measures"]
    assert measures[0]["chords"][0]["text_norm"] == "Bb6/F"
    assert measures[1]["chords"][0]["text_norm"] == "Am7"


def test_chord_chart_parser_uses_rootless_minor_fragments_as_context() -> None:
    image = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.line(image, (405, 196), (435, 150), (0, 0, 0), 5)
    rows = [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(250, 100, 200, 1),
                Boundary(470, 100, 200, 1),
            ],
        )
    ]
    tokens = [
        OCRToken("D-7", (82, 118, 150, 166), 0.94, source="cell_ocr"),
        OCRToken("0-7", (86, 120, 148, 168), 0.41, source="cell_ocr"),
        OCRToken("G61", (278, 118, 348, 168), 0.42, source="cell_ocr"),
        OCRToken("0-7", (282, 120, 344, 168), 0.38, source="cell_ocr"),
        OCRToken("0-", (398, 122, 440, 164), 0.44, source="cell_ocr"),
        OCRToken("F", (408, 168, 430, 224), 0.88, source="cell_ocr"),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
        rows=rows,
    )

    measures = payload["pages"][0]["systems"][0]["measures"]
    assert [chord["text_norm"] for chord in measures[0]["chords"]] == ["Dm7"]
    assert [chord["text_norm"] for chord in measures[1]["chords"]] == [
        "Gm7",
        "Gm7/F",
    ]


def test_chord_chart_parser_does_not_promote_dc_al_fragment_to_chord() -> None:
    image = np.full((300, 360, 3), 255, dtype=np.uint8)
    rows = [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(310, 100, 200, 1),
            ],
        )
    ]
    tokens = [
        OCRToken("D.C.", (70, 205, 120, 226), 0.91, source="cell_ocr"),
        OCRToken("a", (126, 205, 138, 226), 0.72, source="cell_ocr"),
        OCRToken("2nd ending", (145, 205, 250, 226), 0.88, source="cell_ocr"),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
        rows=rows,
    )

    measure = payload["pages"][0]["systems"][0]["measures"][0]
    assert measure["navigation"][0]["type"] == "dc"
    assert measure["chords"] == []


def test_chord_chart_parser_does_not_let_weak_accidental_override_stronger_chord() -> None:
    image = np.full((260, 360, 3), 255, dtype=np.uint8)
    rows = [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(310, 100, 200, 1),
            ],
        )
    ]
    tokens = [
        OCRToken("An7", (70, 118, 150, 170), 0.48, source="page_ocr"),
        OCRToken("Ac7", (72, 118, 152, 170), 0.93, source="cell_ocr_targeted"),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
        rows=rows,
    )

    measure = payload["pages"][0]["systems"][0]["measures"][0]
    assert measure["chords"][0]["text_norm"] == "Amaj7"


def test_chord_chart_parser_attaches_numeric_flat_suffix_fragment() -> None:
    image = np.full((260, 360, 3), 255, dtype=np.uint8)
    rows = [
        ChartRow(
            index=1,
            y_top=100,
            y_bottom=200,
            boundaries=[
                Boundary(50, 100, 200, 1),
                Boundary(310, 100, 200, 1),
            ],
        )
    ]
    tokens = [
        OCRToken(
            "67",
            (70, 118, 145, 170),
            0.48,
            source="cell_ocr_targeted",
            row_index=1,
            col_index=1,
            measure_index=1,
            region="root",
        ),
        OCRToken(
            "769",
            (145, 135, 220, 170),
            0.45,
            source="cell_ocr_targeted",
            row_index=1,
            col_index=1,
            measure_index=1,
            region="suffix_lower_right",
        ),
    ]

    payload = parse_chord_chart_image(
        image=image,
        tokens=tokens,
        ocr_rejects=[],
        job_id="chart-job",
        source_file="chart.png",
        rows=rows,
    )

    measure = payload["pages"][0]["systems"][0]["measures"][0]
    assert measure["chords"][0]["text_norm"] == "G7b9"
    assert measure["chords"][0]["context_fragments"][0]["reason"] == (
        "numeric_6_as_flat_suffix"
    )
