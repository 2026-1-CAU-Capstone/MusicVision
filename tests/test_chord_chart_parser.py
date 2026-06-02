from __future__ import annotations

import cv2
import numpy as np

from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.parser import parse_chord_chart_image


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
