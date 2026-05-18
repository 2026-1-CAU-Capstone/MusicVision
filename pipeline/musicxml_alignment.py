from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def annotate_measure_alignment(
    *,
    chord_result: dict[str, Any],
    musicxml_path: Path,
) -> dict[str, Any]:
    """
    Compare the visual measure sequence with the MusicXML measure sequence.

    When the two sequences align by count, each visual measure is annotated with
    the corresponding MusicXML measure number. If they do not align, the payload
    records the mismatch explicitly instead of pretending an ordinal mapping is
    safe.
    """
    musicxml_measure_numbers = _read_musicxml_measure_numbers(musicxml_path)
    visual_measures = _flatten_visual_measures(chord_result)

    if len(musicxml_measure_numbers) == len(visual_measures):
        for visual_measure, musicxml_measure_number in zip(
            visual_measures,
            musicxml_measure_numbers,
            strict=True,
        ):
            visual_measure["musicxml_measure_number"] = musicxml_measure_number

        return {
            "status": "aligned",
            "musicxml_measure_count": len(musicxml_measure_numbers),
            "visual_measure_count": len(visual_measures),
        }

    return {
        "status": "mismatch",
        "musicxml_measure_count": len(musicxml_measure_numbers),
        "visual_measure_count": len(visual_measures),
    }


def _read_musicxml_measure_numbers(musicxml_path: Path) -> list[str]:
    root = ET.parse(musicxml_path).getroot()
    return [
        measure.attrib.get("number", str(index))
        for index, measure in enumerate(
            (
                element
                for element in root.iter()
                if _local_name(element.tag) == "measure"
            ),
            start=1,
        )
    ]


def _flatten_visual_measures(chord_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        measure
        for page in chord_result.get("pages") or []
        for system in page.get("systems") or []
        for measure in system.get("measures") or []
    ]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]
