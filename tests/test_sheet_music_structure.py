import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

from pipeline.sheet_music_structure import (
    EndingMarker,
    annotate_ending_markers,
    apply_ending_markers_to_musicxml,
    clean_single_staff_redundant_clefs,
    detect_ending_markers,
)


def test_clean_single_staff_redundant_clefs_removes_later_clefs(
    tmp_path: Path,
) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    musicxml_path.write_text(
        """
        <score-partwise>
          <part id="P1">
            <measure number="1">
              <attributes>
                <clef><sign>G</sign><line>2</line></clef>
              </attributes>
            </measure>
            <measure number="2">
              <attributes>
                <clef><sign>C</sign><line>3</line></clef>
              </attributes>
            </measure>
            <measure number="3">
              <attributes>
                <clef><sign>G</sign><line>2</line></clef>
              </attributes>
            </measure>
          </part>
        </score-partwise>
        """,
        encoding="utf-8",
    )

    result = clean_single_staff_redundant_clefs(musicxml_path)

    assert result == {"removed_clefs": 2}
    root = ET.parse(musicxml_path).getroot()
    clefs = [element for element in root.iter() if element.tag == "clef"]
    assert len(clefs) == 1
    assert clefs[0].findtext("sign") == "G"
    assert clefs[0].findtext("line") == "2"


def test_clean_single_staff_redundant_clefs_preserves_multistaff_score(
    tmp_path: Path,
) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    musicxml_path.write_text(
        """
        <score-partwise>
          <part id="P1">
            <measure number="1">
              <attributes>
                <staves>2</staves>
                <clef number="1"><sign>G</sign><line>2</line></clef>
                <clef number="2"><sign>F</sign><line>4</line></clef>
              </attributes>
            </measure>
          </part>
        </score-partwise>
        """,
        encoding="utf-8",
    )

    result = clean_single_staff_redundant_clefs(musicxml_path)

    assert result == {"removed_clefs": 0}
    root = ET.parse(musicxml_path).getroot()
    clefs = [element for element in root.iter() if element.tag == "clef"]
    assert len(clefs) == 2


def test_ending_markers_are_annotated_and_written_to_musicxml(
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
    pages = [
        {
            "systems": [
                {
                    "index": 1,
                    "measures": [
                        {"index": 1, "musicxml_measure_number": "1"},
                        {"index": 2, "musicxml_measure_number": "2"},
                    ],
                }
            ]
        }
    ]
    marker = EndingMarker(
        number=1,
        system_index=1,
        start_measure_index=1,
        end_measure_index=2,
        bbox=(10.0, 20.0, 80.0, 24.0),
    )

    annotate_ending_markers(pages=pages, markers=[marker])
    result = apply_ending_markers_to_musicxml(
        musicxml_path=musicxml_path,
        pages=pages,
        markers=[marker],
    )

    assert result == {"added_endings": 2}
    assert pages[0]["systems"][0]["measures"][0]["form_markers"][0]["number"] == 1
    assert pages[0]["systems"][0]["measures"][1]["form_markers"][0]["number"] == 1

    root = ET.parse(musicxml_path).getroot()
    measures = list(root.iter("measure"))
    start_ending = measures[0].find("./barline/ending")
    stop_ending = measures[1].find("./barline/ending")
    assert start_ending is not None
    assert start_ending.attrib == {"number": "1", "type": "start"}
    assert stop_ending is not None
    assert stop_ending.attrib == {"number": "1", "type": "stop"}


def test_detect_ending_markers_finds_bracket_above_system() -> None:
    image = np.full((160, 260, 3), 255, dtype=np.uint8)
    cv2.line(image, (45, 25), (135, 25), (0, 0, 0), 2)
    cv2.line(image, (45, 25), (45, 50), (0, 0, 0), 2)
    pages = [
        {
            "systems": [
                {
                    "index": 1,
                    "bbox": [30.0, 80.0, 230.0, 140.0],
                    "measures": [
                        {"index": 1, "bbox": [30.0, 80.0, 130.0, 140.0]},
                        {"index": 2, "bbox": [130.0, 80.0, 230.0, 140.0]},
                    ],
                }
            ]
        }
    ]

    markers = detect_ending_markers(image=image, pages=pages)

    assert len(markers) == 1
    assert markers[0].number == 1
    assert markers[0].system_index == 1
    assert markers[0].start_measure_index == 1
    assert markers[0].end_measure_index == 1
