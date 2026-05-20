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

    When the sequences align globally, each visual measure is annotated with the
    corresponding MusicXML measure number. When global counts differ but the
    system counts agree, systems are aligned independently so a local mismatch
    does not invalidate otherwise trustworthy systems.
    """
    musicxml_systems = _read_musicxml_measure_systems(musicxml_path)
    musicxml_measure_numbers = [
        measure_number
        for system in musicxml_systems
        for measure_number in system
    ]
    visual_systems = _flatten_visual_systems(chord_result)
    visual_measures = _flatten_visual_measures(chord_result)
    _clear_musicxml_measure_numbers(visual_measures)

    if len(musicxml_systems) == len(visual_systems):
        system_alignment = _build_system_alignment(
            visual_systems=visual_systems,
            musicxml_systems=musicxml_systems,
            annotate=True,
        )
        aligned_system_count = sum(
            1 for system in system_alignment if system["status"] == "aligned"
        )
        all_systems_aligned = aligned_system_count == len(system_alignment)
        status = "aligned" if all_systems_aligned else "partial"
        if aligned_system_count == 0:
            status = "mismatch"
        return {
            "status": status,
            "musicxml_measure_count": len(musicxml_measure_numbers),
            "visual_measure_count": len(visual_measures),
            "musicxml_system_count": len(musicxml_systems),
            "visual_system_count": len(visual_systems),
            "aligned_system_count": aligned_system_count,
            "mismatched_system_count": len(system_alignment) - aligned_system_count,
            "system_alignment": system_alignment,
        }

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
            "musicxml_system_count": len(musicxml_systems),
            "visual_system_count": len(visual_systems),
            "alignment_strategy": "global_sequence",
            "system_alignment": _build_unmatched_system_alignment(
                visual_systems=visual_systems,
                musicxml_systems=musicxml_systems,
            ),
        }

    return {
        "status": "mismatch",
        "musicxml_measure_count": len(musicxml_measure_numbers),
        "visual_measure_count": len(visual_measures),
        "musicxml_system_count": len(musicxml_systems),
        "visual_system_count": len(visual_systems),
        "system_alignment": _build_unmatched_system_alignment(
            visual_systems=visual_systems,
            musicxml_systems=musicxml_systems,
        ),
    }


def read_musicxml_system_measure_counts(musicxml_path: Path) -> list[int]:
    return [len(system) for system in _read_musicxml_measure_systems(musicxml_path)]


def _read_musicxml_measure_systems(musicxml_path: Path) -> list[list[str]]:
    root = ET.parse(musicxml_path).getroot()
    measures = _primary_part_measures(root)
    systems: list[list[str]] = [[]]

    for index, measure in enumerate(measures, start=1):
        if systems[-1] and _measure_starts_new_system(measure):
            systems.append([])
        systems[-1].append(measure.attrib.get("number", str(index)))

    return [system for system in systems if system]


def _primary_part_measures(root: ET.Element) -> list[ET.Element]:
    for part in root.iter():
        if _local_name(part.tag) != "part":
            continue
        measures = [
            child
            for child in list(part)
            if _local_name(child.tag) == "measure"
        ]
        if measures:
            return measures

    return [
        element
        for element in root.iter()
        if _local_name(element.tag) == "measure"
    ]


def _measure_starts_new_system(measure: ET.Element) -> bool:
    return any(
        _local_name(element.tag) == "print"
        and element.attrib.get("new-system") == "yes"
        for element in measure.iter()
    )


def _flatten_visual_systems(chord_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        system
        for page in chord_result.get("pages") or []
        for system in page.get("systems") or []
    ]


def _flatten_visual_measures(chord_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        measure
        for page in chord_result.get("pages") or []
        for system in page.get("systems") or []
        for measure in system.get("measures") or []
    ]


def _clear_musicxml_measure_numbers(visual_measures: list[dict[str, Any]]) -> None:
    for measure in visual_measures:
        measure.pop("musicxml_measure_number", None)


def _build_system_alignment(
    *,
    visual_systems: list[dict[str, Any]],
    musicxml_systems: list[list[str]],
    annotate: bool,
) -> list[dict[str, Any]]:
    system_alignment: list[dict[str, Any]] = []

    for index, (visual_system, musicxml_measure_numbers) in enumerate(
        zip(visual_systems, musicxml_systems, strict=True),
        start=1,
    ):
        visual_measures = visual_system.get("measures") or []
        status = (
            "aligned"
            if len(visual_measures) == len(musicxml_measure_numbers)
            else "mismatch"
        )

        if annotate and status == "aligned":
            for visual_measure, musicxml_measure_number in zip(
                visual_measures,
                musicxml_measure_numbers,
                strict=True,
            ):
                visual_measure["musicxml_measure_number"] = musicxml_measure_number

        system_alignment.append(
            {
                "visual_system_index": int(visual_system.get("index", index)),
                "musicxml_system_index": index,
                "status": status,
                "musicxml_measure_count": len(musicxml_measure_numbers),
                "visual_measure_count": len(visual_measures),
            }
        )

    return system_alignment


def _build_unmatched_system_alignment(
    *,
    visual_systems: list[dict[str, Any]],
    musicxml_systems: list[list[str]],
) -> list[dict[str, Any]]:
    system_alignment: list[dict[str, Any]] = []
    paired_count = min(len(visual_systems), len(musicxml_systems))

    for index in range(paired_count):
        visual_system = visual_systems[index]
        musicxml_measure_numbers = musicxml_systems[index]
        system_alignment.append(
            {
                "visual_system_index": int(visual_system.get("index", index + 1)),
                "musicxml_system_index": index + 1,
                "status": "unmatched",
                "musicxml_measure_count": len(musicxml_measure_numbers),
                "visual_measure_count": len(visual_system.get("measures") or []),
            }
        )

    for index, visual_system in enumerate(
        visual_systems[paired_count:],
        start=paired_count + 1,
    ):
        system_alignment.append(
            {
                "visual_system_index": int(visual_system.get("index", index)),
                "musicxml_system_index": None,
                "status": "unmatched",
                "musicxml_measure_count": 0,
                "visual_measure_count": len(visual_system.get("measures") or []),
            }
        )

    for index, musicxml_measure_numbers in enumerate(
        musicxml_systems[paired_count:],
        start=paired_count + 1,
    ):
        system_alignment.append(
            {
                "visual_system_index": None,
                "musicxml_system_index": index,
                "status": "unmatched",
                "musicxml_measure_count": len(musicxml_measure_numbers),
                "visual_measure_count": 0,
            }
        )

    return system_alignment


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]
