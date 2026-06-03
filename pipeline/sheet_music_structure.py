from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class EndingMarker:
    number: int
    system_index: int
    start_measure_index: int
    end_measure_index: int
    bbox: tuple[float, float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "ending",
            "number": self.number,
            "system_index": self.system_index,
            "start_measure_index": self.start_measure_index,
            "end_measure_index": self.end_measure_index,
            "bbox": [float(value) for value in self.bbox],
            "source": "visual_ending_bracket_detection",
        }


def clean_single_staff_redundant_clefs(musicxml_path: Path) -> dict[str, Any]:
    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    clef_records = _find_with_parents(root, "clef")
    if len(clef_records) <= 1:
        return {"removed_clefs": 0}

    if not _looks_like_single_staff_score(root, clef_records):
        return {"removed_clefs": 0}

    removed = 0
    for parent, clef in clef_records[1:]:
        parent.remove(clef)
        removed += 1

    if removed:
        tree.write(musicxml_path, encoding="utf-8", xml_declaration=True)

    return {"removed_clefs": removed}


def detect_ending_markers(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
) -> list[EndingMarker]:
    markers: list[EndingMarker] = []
    for page in pages:
        for system in page.get("systems") or []:
            system_markers = _detect_system_ending_markers(image=image, system=system)
            markers.extend(system_markers)
    return markers


def annotate_ending_markers(
    *,
    pages: list[dict[str, Any]],
    markers: list[EndingMarker],
) -> None:
    markers_by_measure: dict[int, list[dict[str, Any]]] = {}
    for marker in markers:
        for measure_index in range(
            marker.start_measure_index,
            marker.end_measure_index + 1,
        ):
            markers_by_measure.setdefault(measure_index, []).append(marker.to_dict())

    if not markers_by_measure:
        return

    for page in pages:
        for system in page.get("systems") or []:
            for measure in system.get("measures") or []:
                measure_markers = markers_by_measure.get(int(measure.get("index") or 0))
                if measure_markers:
                    measure.setdefault("form_markers", []).extend(measure_markers)


def apply_ending_markers_to_musicxml(
    *,
    musicxml_path: Path,
    pages: list[dict[str, Any]],
    markers: list[EndingMarker],
) -> dict[str, Any]:
    if not markers:
        return {"added_endings": 0}

    measure_numbers_by_visual_index = _musicxml_measure_numbers_by_visual_index(pages)
    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    musicxml_measures = _musicxml_measures_by_number(root)

    added = 0
    for marker in markers:
        start_number = measure_numbers_by_visual_index.get(marker.start_measure_index)
        end_number = measure_numbers_by_visual_index.get(marker.end_measure_index)
        if start_number is None or end_number is None:
            continue

        start_measure = musicxml_measures.get(start_number)
        end_measure = musicxml_measures.get(end_number)
        if start_measure is None or end_measure is None:
            continue

        if _add_ending_to_measure(
            start_measure,
            location="left",
            number=marker.number,
            ending_type="start",
        ):
            added += 1
        if _add_ending_to_measure(
            end_measure,
            location="right",
            number=marker.number,
            ending_type="stop",
        ):
            added += 1

    if added:
        tree.write(musicxml_path, encoding="utf-8", xml_declaration=True)

    return {"added_endings": added}


def _find_with_parents(
    root: ET.Element,
    local_name: str,
) -> list[tuple[ET.Element, ET.Element]]:
    result: list[tuple[ET.Element, ET.Element]] = []
    for parent in root.iter():
        for child in list(parent):
            if _local_name(child.tag) == local_name:
                result.append((parent, child))
    return result


def _looks_like_single_staff_score(
    root: ET.Element,
    clef_records: list[tuple[ET.Element, ET.Element]],
) -> bool:
    staff_counts = []
    for element in root.iter():
        if _local_name(element.tag) == "staves" and element.text:
            try:
                staff_counts.append(int(element.text.strip()))
            except ValueError:
                continue
    if staff_counts and max(staff_counts) > 1:
        return False

    clef_numbers = {
        clef.attrib.get("number")
        for _parent, clef in clef_records
        if clef.attrib.get("number") not in {None, "", "1"}
    }
    return not clef_numbers


def _detect_system_ending_markers(
    *,
    image: np.ndarray,
    system: dict[str, Any],
) -> list[EndingMarker]:
    measures = [
        measure
        for measure in system.get("measures") or []
        if _coerce_bbox(measure.get("bbox")) is not None
    ]
    if not measures:
        return []

    system_bbox = _coerce_bbox(system.get("bbox"))
    if system_bbox is None:
        return []

    x0, y0, x1, _y1 = system_bbox
    system_height = max(1.0, system_bbox[3] - system_bbox[1])
    search_top = int(max(0, y0 - max(140.0, system_height * 2.0)))
    search_bottom = int(max(0, y0 - max(2.0, system_height * 0.04)))
    search_left = int(max(0, x0))
    search_right = int(min(image.shape[1], x1))
    if search_right <= search_left or search_bottom <= search_top:
        return []

    crop = image[search_top:search_bottom, search_left:search_right]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(28, int((search_right - search_left) * 0.045)), 2),
    )
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        horizontal,
        connectivity=8,
    )

    candidates: list[tuple[float, float, float, float]] = []
    for index in range(1, count):
        x, y, width, height, area = [int(value) for value in stats[index]]
        if width < max(30, int((search_right - search_left) * 0.04)):
            continue
        if height > 12 or area < width:
            continue

        bbox = (
            float(search_left + x),
            float(search_top + y),
            float(search_left + x + width),
            float(search_top + y + height),
        )
        distance_from_staff_top = y0 - bbox[1]
        if distance_from_staff_top < max(45.0, system_height * 0.75):
            continue
        if _has_left_bracket_hook(binary, x=x, y=y, width=width, height=height):
            candidates.append(bbox)

    if not candidates:
        return []

    candidates = _merge_overlapping_bboxes(candidates)
    markers = []
    for number, bbox in enumerate(sorted(candidates, key=lambda item: item[0]), start=1):
        covered = _measures_for_bracket(bbox, measures)
        if not covered:
            continue
        markers.append(
            EndingMarker(
                number=number,
                system_index=int(system.get("index") or 0),
                start_measure_index=int(covered[0].get("index") or 0),
                end_measure_index=int(covered[-1].get("index") or 0),
                bbox=bbox,
            )
        )
    return markers


def _has_left_bracket_hook(
    binary: np.ndarray,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bool:
    hook_x0 = max(0, x - 5)
    hook_x1 = min(binary.shape[1], x + max(8, int(width * 0.08)))
    hook_y0 = max(0, y)
    hook_y1 = min(binary.shape[0], y + max(12, height + 26))
    roi = binary[hook_y0:hook_y1, hook_x0:hook_x1]
    if roi.size == 0:
        return False

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (2, max(10, int(roi.shape[0] * 0.45))),
    )
    vertical = cv2.morphologyEx(roi, cv2.MORPH_OPEN, vertical_kernel)
    return int(np.count_nonzero(vertical)) >= max(12, int(roi.shape[0] * 0.25))


def _measures_for_bracket(
    bbox: tuple[float, float, float, float],
    measures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bracket_left, _top, bracket_right, _bottom = bbox
    bracket_width = bracket_right - bracket_left
    covered = []
    for measure in measures:
        measure_bbox = _coerce_bbox(measure.get("bbox"))
        if measure_bbox is None:
            continue
        overlap = min(bracket_right, measure_bbox[2]) - max(bracket_left, measure_bbox[0])
        if overlap >= max(8.0, min(bracket_width, measure_bbox[2] - measure_bbox[0]) * 0.12):
            covered.append(measure)
    if covered:
        return covered

    start_measure = _measure_at_x(bracket_left, measures)
    return [start_measure] if start_measure is not None else []


def _measure_at_x(
    x: float,
    measures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for measure in measures:
        bbox = _coerce_bbox(measure.get("bbox"))
        if bbox is not None and bbox[0] <= x <= bbox[2]:
            return measure
    return None


def _merge_overlapping_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    merged: list[tuple[float, float, float, float]] = []
    for bbox in sorted(bboxes, key=lambda item: (item[1], item[0])):
        matched_index = None
        for index, current in enumerate(merged):
            same_line = abs(((bbox[1] + bbox[3]) / 2.0) - ((current[1] + current[3]) / 2.0)) <= 8
            overlaps = min(bbox[2], current[2]) - max(bbox[0], current[0]) >= -8
            if same_line and overlaps:
                matched_index = index
                break
        if matched_index is None:
            merged.append(bbox)
        else:
            current = merged[matched_index]
            merged[matched_index] = (
                min(current[0], bbox[0]),
                min(current[1], bbox[1]),
                max(current[2], bbox[2]),
                max(current[3], bbox[3]),
            )
    return merged


def _musicxml_measure_numbers_by_visual_index(
    pages: list[dict[str, Any]],
) -> dict[int, str]:
    result = {}
    for page in pages:
        for system in page.get("systems") or []:
            for measure in system.get("measures") or []:
                visual_index = measure.get("index")
                musicxml_number = measure.get("musicxml_measure_number")
                if visual_index is not None and musicxml_number is not None:
                    result[int(visual_index)] = str(musicxml_number)
    return result


def _musicxml_measures_by_number(root: ET.Element) -> dict[str, ET.Element]:
    result = {}
    for measure in root.iter():
        if _local_name(measure.tag) == "measure":
            number = measure.attrib.get("number")
            if number is not None:
                result[number] = measure
    return result


def _add_ending_to_measure(
    measure: ET.Element,
    *,
    location: str,
    number: int,
    ending_type: str,
) -> bool:
    for barline in measure:
        if _local_name(barline.tag) != "barline":
            continue
        if barline.attrib.get("location") != location:
            continue
        if _barline_has_ending(barline, number=number, ending_type=ending_type):
            return False
        ending = ET.Element("ending", {"number": str(number), "type": ending_type})
        barline.insert(0, ending)
        return True

    barline = ET.Element("barline", {"location": location})
    ending = ET.Element("ending", {"number": str(number), "type": ending_type})
    barline.append(ending)
    if location == "left":
        measure.insert(0, barline)
    else:
        measure.append(barline)
    return True


def _barline_has_ending(
    barline: ET.Element,
    *,
    number: int,
    ending_type: str,
) -> bool:
    for child in barline:
        if _local_name(child.tag) != "ending":
            continue
        if child.attrib.get("number") == str(number) and child.attrib.get("type") == ending_type:
            return True
    return False


def _coerce_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        return tuple(float(component) for component in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
