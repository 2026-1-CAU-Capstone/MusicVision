from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from pipeline.chord_charts.chord_symbol import (
    ParsedChord,
    parse_chord_symbol,
    repair_numeric_flat_suffix,
)
from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chords.models import quantize_beat


@dataclass
class Boundary:
    x: float
    y_top: float
    y_bottom: float
    component_count: int
    kind: str = "single"


@dataclass
class ChartRow:
    index: int
    y_top: float
    y_bottom: float
    boundaries: list[Boundary]
    section: str | None = None
    ending_number: int | None = None


@dataclass
class MeasureCell:
    index: int
    row_index: int
    col_index: int
    section: str | None
    bbox: tuple[float, float, float, float]
    left_boundary: Boundary
    right_boundary: Boundary
    ending_number: int | None = None
    chords: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    navigation: list[dict[str, Any]] = field(default_factory=list)
    ocr_tokens: list[OCRToken] = field(default_factory=list)


def parse_chord_chart_image(
    *,
    image: np.ndarray,
    tokens: list[OCRToken],
    ocr_rejects: list[dict[str, Any]],
    job_id: str,
    source_file: str,
    overlay_file: str | None = None,
    rows: list[ChartRow] | None = None,
) -> dict[str, Any]:
    rows = rows if rows is not None else detect_chart_grid(image)
    if not rows:
        raise ValueError("Could not detect chord-chart measure grid.")

    warnings: list[str] = []
    time_signature = _extract_time_signature(tokens, rows)
    if time_signature is None:
        if _has_visible_time_signature_region(image, rows):
            time_signature = {
                "text_raw": "4/4",
                "numerator": 4,
                "denominator": 4,
                "source": "visual_region_assumption",
                "confidence": None,
            }
        else:
            time_signature = {
                "text_raw": None,
                "numerator": 4,
                "denominator": 4,
                "source": "default_assumption",
                "confidence": None,
            }
            warnings.append("No time signature was detected; defaulted to 4/4.")

    beats_per_bar = int(time_signature.get("numerator") or 4)
    metadata = _extract_metadata(tokens, rows, image_width=float(image.shape[1]))
    section_markers = _find_section_markers(tokens, rows, image=image)
    _apply_sections(rows, section_markers)
    _apply_visual_endings(image, rows)

    measures = _build_measure_cells(rows)
    cell_token_measure_indices = _cell_token_measure_indices(tokens, measures)
    accepted_tokens: list[dict[str, Any]] = [
        _section_marker_payload(marker)
        for marker in section_markers
        if marker.get("source") == "visual_section_detection"
    ]
    detected_symbols: list[dict[str, Any]] = []
    unassigned_tokens: list[dict[str, Any]] = []

    for token in _expand_chart_tokens(tokens):
        if _is_time_signature_token(token, rows):
            accepted_tokens.append({**token.to_dict(), "kind": "time_signature"})
            continue
        if _is_section_marker_token(token, rows):
            accepted_tokens.append({**token.to_dict(), "kind": "section_marker"})
            continue
        if _is_header_token(token, rows):
            continue

        row = _nearest_row(token, rows)
        if row is None:
            navigation = _parse_navigation(token)
            if navigation is not None:
                detected_symbols.append(navigation)
                accepted_tokens.append({**token.to_dict(), "kind": "navigation"})
                continue

            unassigned_tokens.append(
                {**token.to_dict(), "reason": "outside detected chart grid"}
            )
            continue

        ending_number = _parse_ending_number(token.text)
        if ending_number is not None:
            row.ending_number = ending_number
            accepted_tokens.append({**token.to_dict(), "kind": "ending"})
            detected_symbols.append(
                {
                    "type": "ending_marker",
                    "number": ending_number,
                    "row_index": row.index,
                    "text_raw": token.text,
                    "bbox": list(token.bbox),
                }
            )
            continue

        measure = _measure_for_token(token, measures)
        if measure is None:
            unassigned_tokens.append(
                {**token.to_dict(), "reason": "outside detected measure cells"}
            )
            continue
        if token.source.startswith("cell_ocr"):
            measure.ocr_tokens.append(token)

        navigation = _parse_navigation(token)
        if navigation is not None:
            navigation.update(
                {
                    "measure_index": measure.index,
                    "section": measure.section,
                    "bbox": list(token.bbox),
                }
            )
            measure.navigation.append(navigation)
            accepted_tokens.append({**token.to_dict(), "kind": "navigation"})
            detected_symbols.append(navigation)
            continue

        if (
            measure.index in cell_token_measure_indices
            and not token.source.startswith("cell_ocr")
        ):
            continue

        repeat_symbol = _parse_repeat_symbol(token)
        if repeat_symbol is not None:
            repeat_symbol.update(
                {
                    "measure_index": measure.index,
                    "section": measure.section,
                    "bbox": list(token.bbox),
                }
            )
            measure.symbols.append(repeat_symbol)
            accepted_tokens.append({**token.to_dict(), "kind": "repeat_symbol"})
            detected_symbols.append(repeat_symbol)
            continue

        slash_bass = _parse_slash_bass_token(token.text)
        if slash_bass is not None:
            measure.symbols.append(
                {
                    "type": "slash_bass",
                    "bass": slash_bass,
                    "text_raw": token.text,
                    "bbox": list(token.bbox),
                }
            )
            accepted_tokens.append({**token.to_dict(), "kind": "slash_bass"})
            continue

        parsed_chord = parse_chord_symbol(token.text)
        if parsed_chord is not None:
            measure.chords.append(
                _chord_payload(
                    parsed_chord,
                    bbox=token.bbox,
                    confidence=token.confidence,
                    measure=measure,
                    beats_per_bar=beats_per_bar,
                )
            )
            accepted_tokens.append(
                {
                    **token.to_dict(),
                    "kind": "chord",
                    "text_norm": parsed_chord.text_norm,
                }
            )
            continue

        unassigned_tokens.append({**token.to_dict(), "reason": "unclassified"})

    for measure in measures:
        row = rows[measure.row_index - 1]
        if row.ending_number is not None:
            measure.ending_number = row.ending_number
        _remove_navigation_fragment_chords(measure)
        _apply_ocr_context_to_measure(measure)
        _apply_numeric_alteration_fragments(measure)
        _infer_repeated_rootless_minor_chords(measure, beats_per_bar=beats_per_bar)
        _merge_slash_bass_symbols(measure)
        _merge_vertical_bass_chords(measure, image=image)
        _propagate_same_root_extensions(measure)
        _deduplicate_measure_chords(measure)
        visual_repeat = _detect_visual_percent_repeat(image, measure)
        if visual_repeat is not None and not any(
            symbol.get("type") == "repeat_previous_measure"
            for symbol in measure.symbols
        ):
            measure.symbols.append(visual_repeat)
            detected_symbols.append(visual_repeat)
        measure.symbols = _deduplicate_events(measure.symbols)
        measure.navigation = _deduplicate_events(measure.navigation)

    detected_symbols = _deduplicate_events(detected_symbols)
    _resolve_previous_measure_repeats(measures)
    page_payload = _page_payload(
        image=image,
        rows=rows,
        measures=measures,
    )

    result: dict[str, Any] = {
        "job_id": job_id,
        "source_file": source_file,
        "source_type": "chord_chart",
        "pipeline": "chart_grid_ocr",
        "title": metadata.get("title"),
        "composer": metadata.get("composer"),
        "style": metadata.get("style"),
        "time_signature": time_signature,
        "beats_per_bar": beats_per_bar,
        "flow": _flow_payload(measures),
        "chart_ocr": {
            "backend": "easyocr",
            "accepted_tokens": accepted_tokens,
            "rejected_hits": ocr_rejects,
            "unassigned_tokens": unassigned_tokens,
            "detected_symbols": detected_symbols,
        },
        "pages": [page_payload],
        "warnings": warnings,
    }
    if overlay_file is not None:
        result["overlay_file"] = overlay_file

    return result


def detect_chart_grid(image: np.ndarray) -> list[ChartRow]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel_height = max(45, int(height * 0.025))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, kernel_height))
    vertical_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

    components = _vertical_components(vertical_mask, image_width=width, image_height=height)
    if not components:
        return []

    row_groups = _cluster_components_by_y(components, image_height=height)
    rows: list[ChartRow] = []
    row_index = 1
    for group in row_groups:
        group = _full_height_row_components(group)
        boundaries = _boundaries_from_components(
            group,
            binary=binary,
            image_width=width,
        )
        if len(boundaries) < 2:
            continue

        valid_boundaries = _remove_tiny_leading_intervals(
            boundaries,
            min_gap=max(80.0, width * 0.06),
        )
        if len(valid_boundaries) < 2:
            continue

        y_top = min(boundary.y_top for boundary in valid_boundaries)
        y_bottom = max(boundary.y_bottom for boundary in valid_boundaries)
        rows.append(
            ChartRow(
                index=row_index,
                y_top=float(y_top),
                y_bottom=float(y_bottom),
                boundaries=valid_boundaries,
            )
        )
        row_index += 1

    return rows


def _full_height_row_components(
    components: list[dict[str, float]],
) -> list[dict[str, float]]:
    if not components:
        return []

    max_height = max(component["h"] for component in components)
    min_height = max(55.0, max_height * 0.72)
    return [component for component in components if component["h"] >= min_height]


def _vertical_components(
    vertical_mask: np.ndarray,
    *,
    image_width: int,
    image_height: int,
) -> list[dict[str, float]]:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        vertical_mask,
        connectivity=8,
    )
    components: list[dict[str, float]] = []
    min_height = max(55, int(image_height * 0.025))
    max_width = max(32, int(image_width * 0.025))

    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if h < min_height or w > max_width:
            continue
        if h / max(float(w), 1.0) < 3.0:
            continue
        components.append(
            {
                "x": float(x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
                "area": float(area),
                "cx": float(x + (w - 1) / 2.0),
                "cy": float(y + (h - 1) / 2.0),
                "x1": float(x + w),
                "y1": float(y + h),
            }
        )

    return components


def _cluster_components_by_y(
    components: list[dict[str, float]],
    *,
    image_height: int,
) -> list[list[dict[str, float]]]:
    tolerance = max(70.0, image_height * 0.035)
    groups: list[list[dict[str, float]]] = []

    for component in sorted(components, key=lambda item: item["cy"]):
        matched_group: list[dict[str, float]] | None = None
        for group in groups:
            group_center = float(np.median([item["cy"] for item in group]))
            if abs(component["cy"] - group_center) <= tolerance:
                matched_group = group
                break

        if matched_group is None:
            groups.append([component])
        else:
            matched_group.append(component)

    return groups


def _boundaries_from_components(
    components: list[dict[str, float]],
    *,
    binary: np.ndarray,
    image_width: int,
) -> list[Boundary]:
    x_tolerance = max(12.0, image_width * 0.008)
    sorted_components = sorted(components, key=lambda item: item["cx"])
    groups: list[list[dict[str, float]]] = []

    for component in sorted_components:
        if groups and abs(component["cx"] - np.median([item["cx"] for item in groups[-1]])) <= x_tolerance:
            groups[-1].append(component)
        else:
            groups.append([component])

    boundaries: list[Boundary] = []
    for group in groups:
        x = float(np.median([item["cx"] for item in group]))
        y_top = min(item["y"] for item in group)
        y_bottom = max(item["y1"] for item in group)
        boundary = Boundary(
            x=x,
            y_top=float(y_top),
            y_bottom=float(y_bottom),
            component_count=len(group),
        )
        boundary.kind = _boundary_kind(boundary, group=group, binary=binary)
        boundaries.append(boundary)

    return boundaries


def _boundary_kind(
    boundary: Boundary,
    *,
    group: list[dict[str, float]],
    binary: np.ndarray,
) -> str:
    left_dots = _count_repeat_dots(binary, boundary, side="left")
    right_dots = _count_repeat_dots(binary, boundary, side="right")
    if left_dots >= 2 and right_dots >= 2:
        return "repeat_both"
    if left_dots >= 2:
        return "end_repeat"
    if right_dots >= 2:
        return "start_repeat"
    if len(group) >= 2:
        return "double"
    return "single"


def _count_repeat_dots(binary: np.ndarray, boundary: Boundary, *, side: str) -> int:
    height, width = binary.shape[:2]
    x0 = int(max(0, boundary.x - 55 if side == "left" else boundary.x + 6))
    x1 = int(min(width, boundary.x - 6 if side == "left" else boundary.x + 55))
    y0 = int(max(0, boundary.y_top))
    y1 = int(min(height, boundary.y_bottom))
    if x1 <= x0 or y1 <= y0:
        return 0

    roi = binary[y0:y1, x0:x1]
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        roi,
        connectivity=8,
    )
    dots = 0
    for index in range(1, count):
        _x, _y, w, h, area = stats[index]
        if not (5 <= w <= 40 and 5 <= h <= 40):
            continue
        aspect = w / max(float(h), 1.0)
        fill = area / max(float(w * h), 1.0)
        if 0.55 <= aspect <= 1.45 and fill >= 0.45:
            dots += 1

    return dots


def _remove_tiny_leading_intervals(
    boundaries: list[Boundary],
    *,
    min_gap: float,
) -> list[Boundary]:
    result = list(boundaries)
    while len(result) >= 2 and result[1].x - result[0].x < min_gap:
        result.pop(0)
    return result


def _build_measure_cells(rows: list[ChartRow]) -> list[MeasureCell]:
    measures: list[MeasureCell] = []
    measure_index = 1
    for row in rows:
        for col_index, (left, right) in enumerate(
            zip(row.boundaries, row.boundaries[1:]),
            start=1,
        ):
            if right.x <= left.x:
                continue
            measures.append(
                MeasureCell(
                    index=measure_index,
                    row_index=row.index,
                    col_index=col_index,
                    section=row.section,
                    bbox=(left.x, row.y_top, right.x, row.y_bottom),
                    left_boundary=left,
                    right_boundary=right,
                    ending_number=row.ending_number,
                )
            )
            measure_index += 1

    return measures


def _cell_token_measure_indices(
    tokens: list[OCRToken],
    measures: list[MeasureCell],
) -> set[int]:
    indices: set[int] = set()
    for token in tokens:
        if not token.source.startswith("cell_ocr"):
            continue

        measure = _measure_for_token(token, measures)
        if measure is not None:
            indices.add(measure.index)

    return indices


def _extract_metadata(
    tokens: list[OCRToken],
    rows: list[ChartRow],
    *,
    image_width: float,
) -> dict[str, str | None]:
    first_y = rows[0].y_top
    header_tokens = [
        token for token in tokens if token.bbox[3] < first_y - 8 and len(token.text.strip()) > 1
    ]
    title_tokens = [
        token
        for token in header_tokens
        if image_width * 0.25 <= token.cx <= image_width * 0.75
        and not token.text.strip().startswith("(")
    ]
    composer_tokens = [
        token for token in header_tokens if token.cx > image_width * 0.58
    ]
    style_tokens = [
        token
        for token in header_tokens
        if token.cx < image_width * 0.35 or token.text.strip().startswith("(")
    ]

    return {
        "title": _join_tokens_same_line(title_tokens),
        "composer": _join_tokens_same_line(composer_tokens),
        "style": _clean_wrapped_text(_join_tokens_same_line(style_tokens)),
    }


def _extract_time_signature(
    tokens: list[OCRToken],
    rows: list[ChartRow],
) -> dict[str, Any] | None:
    first_row = rows[0]
    left_x = first_row.boundaries[0].x
    candidates = [
        token
        for token in tokens
        if token.cx < left_x + 55
        and first_row.y_top - 40 <= token.cy <= first_row.y_bottom + 20
        and bool(re.fullmatch(r"[0-9/:\s]+", token.text.strip()))
    ]
    raw_text = " ".join(token.text for token in sorted(candidates, key=lambda item: item.cy))
    compact = re.sub(r"\s+", "", raw_text)
    match = re.search(r"(?P<num>\d+)[/:]?(?P<den>\d+)", compact)
    if match is None:
        return None

    try:
        numerator = int(match.group("num")[0])
        denominator = int(match.group("den")[-1])
    except ValueError:
        return None

    return {
        "text_raw": raw_text or compact,
        "numerator": numerator,
        "denominator": denominator,
        "source": "ocr",
        "confidence": _average_confidence(candidates),
    }


def _has_visible_time_signature_region(image: np.ndarray, rows: list[ChartRow]) -> bool:
    first_row = rows[0]
    x0 = 0
    x1 = int(max(0, first_row.boundaries[0].x - 8))
    y0 = int(max(0, first_row.y_top - 8))
    y1 = int(min(image.shape[0], first_row.y_bottom + 8))
    if x1 <= x0 or y1 <= y0:
        return False

    crop = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return int(np.count_nonzero(binary)) >= max(200, int(binary.size * 0.08))


def _find_section_markers(
    tokens: list[OCRToken],
    rows: list[ChartRow],
    *,
    image: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for row in rows:
        left_x = row.boundaries[0].x
        for token in tokens:
            text = token.text.strip().upper()
            if not re.fullmatch(r"[A-Z]", text):
                continue
            if token.cx > left_x + 12:
                continue
            if row.y_top - 95 <= token.cy <= row.y_top + 35:
                markers.append(
                    {
                        "section": text,
                        "row_index": row.index,
                        "bbox": list(token.bbox),
                        "confidence": token.confidence,
                        "source": token.source,
                    }
                )
                break

    if image is not None:
        markers.extend(_find_visual_section_markers(image, rows, markers))

    return sorted(markers, key=lambda marker: int(marker["row_index"]))


def _find_visual_section_markers(
    image: np.ndarray,
    rows: list[ChartRow],
    existing_markers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    marked_rows = {int(marker["row_index"]) for marker in existing_markers}
    markers: list[dict[str, Any]] = []

    for row in rows:
        if row.index in marked_rows:
            continue

        bbox = _visual_section_marker_bbox(image, row)
        if bbox is None:
            continue

        label, confidence = _classify_visual_section_marker(image, bbox)
        if label is None:
            continue

        markers.append(
            {
                "section": label,
                "row_index": row.index,
                "bbox": [float(value) for value in bbox],
                "confidence": confidence,
                "source": "visual_section_detection",
            }
        )

    return markers


def _visual_section_marker_bbox(
    image: np.ndarray,
    row: ChartRow,
) -> tuple[float, float, float, float] | None:
    height, width = image.shape[:2]
    marker_x0 = int(max(0, row.boundaries[0].x - 70))
    marker_x1 = int(min(width, row.boundaries[0].x + 20))
    marker_y0 = int(max(0, row.y_top - 90))
    marker_y1 = int(min(height, row.y_top + 10))
    if marker_x1 <= marker_x0 or marker_y1 <= marker_y0:
        return None

    crop = image[marker_y0:marker_y1, marker_x0:marker_x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    binary = np.zeros_like(gray, dtype=np.uint8)
    binary[gray < 80] = 255
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )

    candidates: list[dict[str, float]] = []
    row_height = max(1.0, row.y_bottom - row.y_top)
    for index in range(1, count):
        x, y, component_width, component_height, area = [
            float(value) for value in stats[index]
        ]
        if not (20.0 <= component_width <= max(60.0, row_height * 0.58)):
            continue
        if not (max(26.0, row_height * 0.22) <= component_height <= row_height * 0.62):
            continue

        fill_ratio = area / max(component_width * component_height, 1.0)
        if fill_ratio < 0.50:
            continue

        abs_x0 = marker_x0 + x
        abs_y0 = marker_y0 + y
        abs_x1 = abs_x0 + component_width
        abs_y1 = abs_y0 + component_height
        if abs_x0 > row.boundaries[0].x + 5:
            continue
        if not (row.y_top - 75 <= (abs_y0 + abs_y1) / 2.0 <= row.y_top):
            continue

        candidates.append(
            {
                "x0": abs_x0,
                "y0": abs_y0,
                "x1": abs_x1,
                "y1": abs_y1,
                "area": area,
                "fill_ratio": fill_ratio,
            }
        )

    if not candidates:
        return None

    best = max(candidates, key=lambda item: (item["area"], item["fill_ratio"]))
    return best["x0"], best["y0"], best["x1"], best["y1"]


def _classify_visual_section_marker(
    image: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> tuple[str | None, float | None]:
    marker = _visual_section_marker_glyph_mask(image, bbox)
    if marker is None:
        return None, None

    feature_label = _visual_section_marker_feature_label(marker)
    if feature_label is not None:
        return feature_label, 0.78

    scores = {
        letter: _binary_mask_iou(marker, _visual_section_letter_template(letter))
        for letter in "ABCDEFG"
    }
    label, score = max(scores.items(), key=lambda item: item[1])
    if score < 0.40:
        return None, None
    return label, float(score)


def _visual_section_marker_glyph_mask(
    image: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> np.ndarray | None:
    height, width = image.shape[:2]
    x0, y0, x1, y1 = [int(round(value)) for value in bbox]
    x0 = max(0, min(width, x0 + 3))
    x1 = max(0, min(width, x1 - 3))
    y0 = max(0, min(height, y0 + 3))
    y1 = max(0, min(height, y1 - 3))
    if x1 <= x0 or y1 <= y0:
        return None

    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
    mask = np.zeros_like(gray, dtype=np.uint8)
    mask[gray > 180] = 255
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None

    glyph = mask[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1]
    if glyph.size == 0:
        return None
    return cv2.resize(glyph, (28, 32), interpolation=cv2.INTER_AREA)


def _visual_section_marker_feature_label(mask: np.ndarray) -> str | None:
    binary = mask > 127
    if not np.any(binary):
        return None

    height, width = binary.shape
    left = int(np.count_nonzero(binary[:, : width // 3]))
    right = int(np.count_nonzero(binary[:, (width * 2) // 3 :]))
    top = int(np.count_nonzero(binary[: height // 3, :]))
    middle = int(np.count_nonzero(binary[height // 3 : (height * 2) // 3, :]))
    bottom = int(np.count_nonzero(binary[(height * 2) // 3 :, :]))

    if (
        left > right * 1.55
        and top > middle * 1.20
        and bottom > middle * 1.20
    ):
        return "C"
    return None


def _visual_section_letter_template(letter: str) -> np.ndarray:
    canvas = np.zeros((37, 32), dtype=np.uint8)
    cv2.putText(
        canvas,
        letter,
        (2, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.25,
        255,
        3,
        cv2.LINE_AA,
    )
    ys, xs = np.where(canvas > 0)
    if len(xs) == 0:
        return cv2.resize(canvas, (28, 32), interpolation=cv2.INTER_AREA)
    glyph = canvas[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1]
    return cv2.resize(glyph, (28, 32), interpolation=cv2.INTER_AREA)


def _binary_mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    left_binary = left > 127
    right_binary = right > 127
    union = int(np.count_nonzero(left_binary | right_binary))
    if union == 0:
        return 0.0
    intersection = int(np.count_nonzero(left_binary & right_binary))
    return intersection / union


def _section_marker_payload(marker: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": marker["section"],
        "bbox": [float(value) for value in marker["bbox"]],
        "confidence": marker.get("confidence"),
        "source": marker.get("source"),
        "kind": "section_marker",
        "row_index": marker.get("row_index"),
    }


def _apply_sections(rows: list[ChartRow], markers: list[dict[str, Any]]) -> None:
    marker_by_row = {marker["row_index"]: marker["section"] for marker in markers}
    current_section: str | None = None
    for row in rows:
        if row.index in marker_by_row:
            current_section = str(marker_by_row[row.index])
        row.section = current_section


def _apply_visual_endings(image: np.ndarray, rows: list[ChartRow]) -> None:
    ending_rows = [row for row in rows if _has_ending_bracket_above_row(image, row)]
    for number, row in enumerate(ending_rows, start=1):
        if row.ending_number is None:
            row.ending_number = number


def _has_ending_bracket_above_row(image: np.ndarray, row: ChartRow) -> bool:
    x0 = int(max(0, row.boundaries[0].x - 5))
    x1 = int(min(image.shape[1], row.boundaries[1].x + 15))
    y0 = int(max(0, row.y_top - 95))
    y1 = int(max(0, row.y_top - 4))
    if x1 <= x0 or y1 <= y0:
        return False

    crop = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (55, 3))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        horizontal,
        connectivity=8,
    )

    for index in range(1, count):
        _x, _y, width, height, area = stats[index]
        if width >= 80 and height <= 12 and area >= 120:
            return True

    return False


def _expand_chart_tokens(tokens: list[OCRToken]) -> list[OCRToken]:
    expanded: list[OCRToken] = []
    for token in tokens:
        if _parse_navigation(token) is not None:
            expanded.append(token)
            continue

        parts = token.text.split()
        if len(parts) <= 1:
            expanded.append(token)
            continue

        x0, y0, x1, y1 = token.bbox
        total_chars = sum(len(part) for part in parts)
        if total_chars == 0:
            expanded.append(token)
            continue

        cursor = x0
        width = x1 - x0
        for part in parts:
            part_width = width * (len(part) / total_chars)
            expanded.append(
                OCRToken(
                    text=part,
                    bbox=(cursor, y0, cursor + part_width, y1),
                    confidence=token.confidence,
                    source=token.source,
                )
            )
            cursor += part_width

    return expanded


def _is_header_token(token: OCRToken, rows: list[ChartRow]) -> bool:
    return token.bbox[3] < rows[0].y_top - 8


def _is_time_signature_token(token: OCRToken, rows: list[ChartRow]) -> bool:
    first_row = rows[0]
    return (
        token.cx < first_row.boundaries[0].x + 55
        and first_row.y_top - 40 <= token.cy <= first_row.y_bottom + 20
        and bool(re.fullmatch(r"[0-9/:\s]+", token.text.strip()))
    )


def _is_section_marker_token(token: OCRToken, rows: list[ChartRow]) -> bool:
    text = token.text.strip().upper()
    if not re.fullmatch(r"[A-Z]", text):
        return False

    for row in rows:
        if token.cx <= row.boundaries[0].x + 12 and row.y_top - 95 <= token.cy <= row.y_top + 35:
            return True

    return False


def _nearest_row(token: OCRToken, rows: list[ChartRow]) -> ChartRow | None:
    candidates = [
        row
        for row in rows
        if row.y_top - 55 <= token.cy <= row.y_bottom + 55
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda row: abs(token.cy - ((row.y_top + row.y_bottom) / 2.0)),
    )


def _measure_for_token(
    token: OCRToken,
    measures: list[MeasureCell],
) -> MeasureCell | None:
    candidates = [
        measure
        for measure in measures
        if measure.bbox[0] - 8 <= token.cx <= measure.bbox[2] + 8
        and measure.bbox[1] - 60 <= token.cy <= measure.bbox[3] + 60
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda measure: (
            abs(token.cy - ((measure.bbox[1] + measure.bbox[3]) / 2.0)),
            abs(token.cx - ((measure.bbox[0] + measure.bbox[2]) / 2.0)),
        ),
    )


def _parse_ending_number(text: str) -> int | None:
    match = re.fullmatch(r"\[?\s*([12])\.?", text.strip())
    if match is None:
        return None
    return int(match.group(1))


def _parse_repeat_symbol(token: OCRToken) -> dict[str, Any] | None:
    if "%" not in token.text:
        return None

    return {
        "type": "repeat_previous_measure",
        "text_raw": token.text,
    }


def _parse_navigation(token: OCRToken) -> dict[str, Any] | None:
    text = token.text.strip()
    lower = text.lower().replace(" ", "")
    if lower == "fine":
        return {
            "type": "fine",
            "text_raw": text,
        }
    if lower.startswith(("d.c.", "dc")):
        payload: dict[str, Any] = {
            "type": "dc",
            "text_raw": text,
        }
        ending_match = re.search(r"(\d+)(?:st|nd|rd|th)?ending", lower)
        if ending_match:
            payload["type"] = "dc_al_ending"
            payload["target_ending"] = int(ending_match.group(1))
        return payload

    return None


def _parse_slash_bass_token(text: str) -> str | None:
    stripped = text.strip()
    match = re.fullmatch(r"/\s*([A-Ga-g])([#b]?)", stripped)
    if match is None:
        return None

    return f"{match.group(1).upper()}{match.group(2)}"


def _chord_payload(
    parsed_chord: ParsedChord,
    *,
    bbox: tuple[float, float, float, float],
    confidence: float | None,
    measure: MeasureCell,
    beats_per_bar: int,
) -> dict[str, Any]:
    payload = parsed_chord.to_dict()
    payload.update(
        {
            "bbox": [float(value) for value in bbox],
            "confidence": confidence,
            "beat": quantize_beat(
                (bbox[0] + bbox[2]) / 2.0,
                measure.bbox[0],
                measure.bbox[2],
                beats_per_bar,
            ),
        }
    )
    return payload


def _merge_slash_bass_symbols(measure: MeasureCell) -> None:
    slash_symbols = [
        symbol for symbol in measure.symbols if symbol.get("type") == "slash_bass"
    ]
    if not slash_symbols or not measure.chords:
        return

    for symbol in slash_symbols:
        bbox = symbol.get("bbox") or [0, 0, 0, 0]
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0
        target = min(
            measure.chords,
            key=lambda chord: abs(
                cx
                - (
                    float(chord["bbox"][0])
                    + float(chord["bbox"][2])
                )
                / 2.0
            ),
        )
        if target["components"].get("bass") is None:
            _attach_bass_to_chord(target, str(symbol["bass"]), str(symbol["text_raw"]))


def _merge_vertical_bass_chords(measure: MeasureCell, *, image: np.ndarray) -> None:
    if len(measure.chords) < 2:
        return

    row_y0, row_y1 = measure.bbox[1], measure.bbox[3]
    has_visual_slash = _has_visual_slash_in_measure(image, measure)
    to_remove: set[int] = set()

    for index, chord in enumerate(measure.chords):
        bass = _bass_root_from_lower_chord(
            chord,
            measure=measure,
            has_visual_slash=has_visual_slash,
        )
        if bass is None:
            continue
        chord_bbox = chord.get("bbox") or [0, 0, 0, 0]
        chord_cx = (float(chord_bbox[0]) + float(chord_bbox[2])) / 2.0
        chord_cy = (float(chord_bbox[1]) + float(chord_bbox[3])) / 2.0

        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for target_index, target in enumerate(measure.chords):
            if target_index == index or target_index in to_remove:
                continue
            target_bbox = target.get("bbox") or [0, 0, 0, 0]
            target_cx = (float(target_bbox[0]) + float(target_bbox[2])) / 2.0
            target_cy = (float(target_bbox[1]) + float(target_bbox[3])) / 2.0
            if target_cy >= chord_cy or target["components"].get("bass") is not None:
                continue
            candidates.append((abs(chord_cx - target_cx), target_index, target))

        if not candidates:
            continue

        distance, _target_index, target = min(candidates, key=lambda item: item[0])
        max_distance = max(45.0, (measure.bbox[2] - measure.bbox[0]) * 0.22)
        if has_visual_slash:
            max_distance = max(max_distance, (measure.bbox[2] - measure.bbox[0]) * 0.34)
        if distance <= max_distance:
            _attach_bass_to_chord(target, bass, str(chord["text_raw"]))
            to_remove.add(index)

    if to_remove:
        measure.chords = [
            chord for index, chord in enumerate(measure.chords) if index not in to_remove
        ]


def _attach_bass_to_chord(
    chord: dict[str, Any],
    bass: str,
    raw_bass_text: str,
) -> None:
    chord["components"]["bass"] = bass
    chord["text_raw"] = f"{chord['text_raw']}/{raw_bass_text.lstrip('/')}"
    chord["text_norm"] = f"{chord['text_norm'].split('/')[0]}/{bass}"
    chord["text_display"] = chord["text_raw"]


def _remove_navigation_fragment_chords(measure: MeasureCell) -> None:
    if not measure.chords or not any(
        _raw_has_navigation_context(token.text) for token in measure.ocr_tokens
    ):
        return

    measure.chords = [
        chord
        for chord in measure.chords
        if not _is_lower_navigation_a_chord(chord, measure)
    ]


def _is_lower_navigation_a_chord(
    chord: dict[str, Any],
    measure: MeasureCell,
) -> bool:
    raw = str(chord.get("text_raw") or "").strip()
    if raw not in {"a", "a/a"}:
        return False

    components = chord.get("components") or {}
    if components.get("root") != "A" or components.get("accidental") is not None:
        return False
    if components.get("quality") != "major":
        return False
    if components.get("extensions") or components.get("alterations"):
        return False

    chord_bbox = chord.get("bbox") or [0, 0, 0, 0]
    chord_cy = (float(chord_bbox[1]) + float(chord_bbox[3])) / 2.0
    lower_navigation_y = measure.bbox[1] + (measure.bbox[3] - measure.bbox[1]) * 0.74
    return chord_cy >= lower_navigation_y


def _raw_has_navigation_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.strip().lower())
    return (
        compact.startswith(("d.c", "dc"))
        or "ending" in compact
        or compact in {"fine", "al", "1st", "2nd", "3rd", "4th"}
    )


def _bass_root_from_lower_chord(
    chord: dict[str, Any],
    *,
    measure: MeasureCell,
    has_visual_slash: bool,
) -> str | None:
    if not _is_lower_bass_chord_candidate(chord, measure):
        return None

    components = chord.get("components") or {}
    raw = str(chord.get("text_raw") or "").strip()
    raw_compact = raw.replace("\u266d", "b").replace("\ue260", "b")
    raw_compact = raw_compact.replace("\u266f", "#").replace("\ue262", "#")

    if has_visual_slash and raw == "e" and components.get("root") == "E":
        return "F"
    if not re.fullmatch(r"[A-Ga-g](?:[#b])?", raw_compact):
        return None

    return f"{components['root']}{components.get('accidental') or ''}"


def _is_lower_bass_chord_candidate(
    chord: dict[str, Any],
    measure: MeasureCell,
) -> bool:
    components = chord.get("components") or {}
    if components.get("quality") != "major":
        return False
    if components.get("extensions") or components.get("alterations") or components.get("bass"):
        return False

    chord_bbox = chord.get("bbox") or [0, 0, 0, 0]
    chord_cy = (float(chord_bbox[1]) + float(chord_bbox[3])) / 2.0
    lower_threshold = measure.bbox[1] + (measure.bbox[3] - measure.bbox[1]) * 0.62
    if chord_cy < lower_threshold:
        return False

    raw = str(chord.get("text_raw") or "").strip()
    raw_compact = raw.replace("\u266d", "b").replace("\ue260", "b")
    raw_compact = raw_compact.replace("\u266f", "#").replace("\ue262", "#")
    return bool(re.fullmatch(r"[A-Ga-g](?:[#b])?", raw_compact) or raw == "e")


def _has_visual_slash_in_measure(image: np.ndarray, measure: MeasureCell) -> bool:
    x0, y0, x1, y1 = [int(round(value)) for value in measure.bbox]
    height = max(1, y1 - y0)
    y0 = int(max(0, y0 + height * 0.32))
    y1 = int(min(image.shape[0], y1 + height * 0.42))
    x0 = int(max(0, x0 + 4))
    x1 = int(min(image.shape[1], x1 - 4))
    if x1 <= x0 or y1 <= y0:
        return False

    crop = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180.0,
        threshold=22,
        minLineLength=max(24, int(min(binary.shape[:2]) * 0.18)),
        maxLineGap=10,
    )
    if lines is None:
        return False

    for line in lines[:, 0]:
        lx0, ly0, lx1, ly1 = [float(value) for value in line]
        dx = lx1 - lx0
        if dx == 0:
            continue
        angle = np.degrees(np.arctan2(ly1 - ly0, dx))
        if -75.0 <= angle <= -20.0:
            return True
    return False


def _apply_ocr_context_to_measure(measure: MeasureCell) -> None:
    if not measure.chords:
        return

    for group in _chord_groups(measure):
        chords = group["chords"]
        tokens = group["tokens"]
        if not chords:
            continue

        context_chords = [
            chord for chord in chords if not _is_lower_bass_chord_candidate(chord, measure)
        ]
        if not context_chords:
            continue

        best = max(context_chords, key=_chord_score)
        components = best.get("components") or {}
        root = str(components.get("root") or "")
        if not root:
            continue

        accidental = components.get("accidental")
        if components.get("alterations"):
            continue

        best_confidence = float(best.get("confidence") or 0.0)
        for chord in context_chords:
            other = chord.get("components") or {}
            if (
                other.get("root") == root
                and other.get("accidental")
                and float(chord.get("confidence") or 0.0) >= best_confidence - 0.05
            ):
                accidental = other.get("accidental")
                break

        raw_texts = [str(token.text) for token in tokens]
        minor_cue = any(_raw_has_minor_cue(text) for text in raw_texts) or any(
            (chord.get("components") or {}).get("quality") == "minor"
            for chord in context_chords
        )
        major_seventh_cue = any(_chord_has_major_seventh(chord) for chord in context_chords)
        sixth_cue = any(_chord_has_extension(chord, "6") for chord in context_chords) or any(
            _raw_is_standalone_extension(text, "6") for text in raw_texts
        )
        seventh_cue = (
            major_seventh_cue
            or any(_chord_has_extension(chord, "7") for chord in context_chords)
            or any(_raw_has_seventh_cue(text) for text in raw_texts)
        )

        quality = components.get("quality")
        if quality in {"diminished", "half_diminished"}:
            continue

        if major_seventh_cue:
            body = "mMaj7" if minor_cue else "maj7"
        elif minor_cue:
            if seventh_cue:
                body = "m7"
            elif sixth_cue:
                body = "m6"
            else:
                body = "m"
        elif sixth_cue:
            body = "6"
        elif seventh_cue:
            body = "7"
        else:
            continue

        _rewrite_chord(best, root=root, accidental=accidental, body=body)


def _apply_numeric_alteration_fragments(measure: MeasureCell) -> None:
    if not measure.chords:
        return

    measure_width = measure.bbox[2] - measure.bbox[0]
    max_suffix_distance = max(70.0, measure_width * 0.34)
    left_tolerance = max(12.0, measure_width * 0.04)

    for token in measure.ocr_tokens:
        body = repair_numeric_flat_suffix(token.text)
        if body is None:
            continue

        candidates: list[tuple[float, dict[str, Any]]] = []
        for chord in measure.chords:
            if _is_lower_bass_chord_candidate(chord, measure):
                continue
            components = chord.get("components") or {}
            if not components.get("root"):
                continue
            if components.get("quality") in {
                "minor",
                "minor_major",
                "diminished",
                "half_diminished",
            }:
                continue

            distance = token.cx - _bbox_center_x(chord.get("bbox"))
            if -left_tolerance <= distance <= max_suffix_distance:
                candidates.append((abs(distance), chord))

        if not candidates:
            continue

        _distance, target = min(candidates, key=lambda item: item[0])
        components = target.get("components") or {}
        root = str(components.get("root") or "")
        if not root:
            continue

        target.setdefault("context_fragments", []).append(
            {
                "text_raw": token.text,
                "text_norm": body,
                "bbox": [float(value) for value in token.bbox],
                "confidence": token.confidence,
                "source": token.source,
                "region": token.region,
                "reason": "numeric_6_as_flat_suffix",
            }
        )
        _rewrite_chord(
            target,
            root=root,
            accidental=components.get("accidental"),
            body=body,
        )


def _infer_repeated_rootless_minor_chords(
    measure: MeasureCell,
    *,
    beats_per_bar: int,
) -> None:
    if not measure.chords:
        return

    width = measure.bbox[2] - measure.bbox[0]
    group_threshold = max(40.0, width * 0.16)
    repeat_threshold = max(80.0, width * 0.55)
    source_chords = list(measure.chords)

    for token in measure.ocr_tokens:
        if not _raw_is_rootless_minor_fragment(token.text):
            continue
        token_center = token.cx
        if any(
            abs(token_center - _bbox_center_x(chord.get("bbox"))) <= group_threshold
            for chord in source_chords
            if not _is_lower_bass_chord_candidate(chord, measure)
        ):
            continue

        candidates = []
        for chord in measure.chords:
            if _is_lower_bass_chord_candidate(chord, measure):
                continue
            chord_center = _bbox_center_x(chord.get("bbox"))
            distance = token_center - chord_center
            if 0 < distance <= repeat_threshold:
                candidates.append((distance, chord))
        if not candidates:
            continue

        _distance, template = min(candidates, key=lambda item: item[0])
        components = template.get("components") or {}
        root = components.get("root")
        if not root:
            continue

        template_body = _body_from_chord(template)
        body = template_body if template_body and template_body.startswith("m") else "m7"
        if "7" not in token.text and template_body is None:
            body = "m"

        parsed = parse_chord_symbol(
            f"{root}{components.get('accidental') or ''}{body}"
        )
        if parsed is None:
            continue

        measure.chords.append(
            _chord_payload(
                parsed,
                bbox=token.bbox,
                confidence=token.confidence,
                measure=measure,
                beats_per_bar=beats_per_bar,
            )
        )


def _chord_groups(measure: MeasureCell) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    threshold = max(40.0, (measure.bbox[2] - measure.bbox[0]) * 0.16)

    for chord in sorted(measure.chords, key=lambda item: _bbox_center_x(item.get("bbox"))):
        center = _bbox_center_x(chord.get("bbox"))
        matched: dict[str, Any] | None = None
        for group in groups:
            if abs(center - group["center"]) <= threshold:
                matched = group
                break
        if matched is None:
            groups.append({"center": center, "chords": [chord], "tokens": []})
        else:
            matched["chords"].append(chord)
            matched["center"] = float(
                np.mean([_bbox_center_x(item.get("bbox")) for item in matched["chords"]])
            )

    for token in measure.ocr_tokens:
        center = token.cx
        matched = None
        for group in groups:
            if abs(center - group["center"]) <= threshold:
                matched = group
                break
        if matched is not None:
            matched["tokens"].append(token)

    return groups


def _deduplicate_measure_chords(measure: MeasureCell) -> None:
    if len(measure.chords) < 2:
        return

    groups = _chord_groups(measure)
    kept: list[dict[str, Any]] = []
    for group in groups:
        chords = group["chords"]
        if not chords:
            continue
        kept.append(max(chords, key=_chord_score))

    kept.sort(key=lambda chord: _bbox_center_x(chord.get("bbox")))
    measure.chords = kept


def _propagate_same_root_extensions(measure: MeasureCell) -> None:
    if len(measure.chords) < 2:
        return

    templates: dict[tuple[object, object, object], dict[str, Any]] = {}
    for chord in measure.chords:
        components = chord.get("components") or {}
        if not components.get("extensions"):
            continue
        key = (
            components.get("root"),
            components.get("accidental"),
            components.get("quality"),
        )
        current = templates.get(key)
        if current is None or _chord_score(chord) > _chord_score(current):
            templates[key] = chord

    for chord in measure.chords:
        components = chord.get("components") or {}
        if components.get("extensions") or components.get("alterations"):
            continue
        key = (
            components.get("root"),
            components.get("accidental"),
            components.get("quality"),
        )
        template = templates.get(key)
        if template is None:
            continue
        body = _body_from_chord(template)
        if body:
            _rewrite_chord(
                chord,
                root=str(components.get("root") or ""),
                accidental=components.get("accidental"),
                body=body,
            )


def _rewrite_chord(
    chord: dict[str, Any],
    *,
    root: str,
    accidental: object,
    body: str,
) -> None:
    accidental_text = str(accidental or "")
    text_norm = f"{root}{accidental_text}{body}"
    bass = (chord.get("components") or {}).get("bass")
    if bass:
        text_norm = f"{text_norm}/{bass}"

    parsed = parse_chord_symbol(text_norm)
    if parsed is not None:
        chord["text_norm"] = parsed.text_norm
        chord["components"] = parsed.to_dict()["components"]
        return

    chord["text_norm"] = text_norm
    chord["components"] = {
        "root": root,
        "accidental": accidental_text or None,
        "quality": _quality_from_body(body),
        "extensions": _extensions_from_body(body),
        "alterations": _alterations_from_body(body),
        "bass": bass,
    }


def _chord_score(chord: dict[str, Any]) -> float:
    components = chord.get("components") or {}
    score = float(chord.get("confidence") or 0.0) * 3.0
    score += len(str(chord.get("text_norm") or "")) * 0.20
    if components.get("accidental"):
        score += 0.6
    if components.get("quality") not in {None, "major"}:
        score += 0.8
    if components.get("extensions"):
        score += 0.8
    if components.get("alterations"):
        score += 1.0
    if components.get("bass"):
        score += 1.2
    if "maj7" in str(chord.get("text_norm") or ""):
        score += 0.8
    return score


def _deduplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    for event in events:
        if any(_same_event(event, existing) for existing in deduplicated):
            continue
        deduplicated.append(event)
    return deduplicated


def _same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _event_identity(left) != _event_identity(right):
        return False

    left_bbox = left.get("bbox")
    right_bbox = right.get("bbox")
    if _bbox_iou(left_bbox, right_bbox) >= 0.75:
        return True

    left_center = _bbox_center(left_bbox)
    right_center = _bbox_center(right_bbox)
    if left_center is None or right_center is None:
        return True

    return (
        abs(left_center[0] - right_center[0]) <= 12.0
        and abs(left_center[1] - right_center[1]) <= 12.0
    )


def _event_identity(event: dict[str, Any]) -> tuple[object, ...]:
    text = re.sub(r"\s+", "", str(event.get("text_raw") or "")).lower()
    return (
        event.get("type"),
        event.get("measure_index"),
        event.get("row_index"),
        event.get("section"),
        event.get("number"),
        event.get("target_ending"),
        text,
    )


def _bbox_center(bbox: object) -> tuple[float, float] | None:
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    return (
        (float(bbox[0]) + float(bbox[2])) / 2.0,
        (float(bbox[1]) + float(bbox[3])) / 2.0,
    )


def _bbox_iou(left: object, right: object) -> float:
    if (
        not isinstance(left, list | tuple)
        or not isinstance(right, list | tuple)
        or len(left) != 4
        or len(right) != 4
    ):
        return 0.0

    lx0, ly0, lx1, ly1 = [float(value) for value in left]
    rx0, ry0, rx1, ry1 = [float(value) for value in right]
    ix0 = max(lx0, rx0)
    iy0 = max(ly0, ry0)
    ix1 = min(lx1, rx1)
    iy1 = min(ly1, ry1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if intersection <= 0.0:
        return 0.0

    left_area = max(0.0, lx1 - lx0) * max(0.0, ly1 - ly0)
    right_area = max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0)
    union = left_area + right_area - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def _bbox_center_x(bbox: object) -> float:
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return 0.0
    return (float(bbox[0]) + float(bbox[2])) / 2.0


def _raw_has_minor_cue(text: str) -> bool:
    return (
        "-" in text
        or "\u2212" in text
        or "\u2013" in text
        or "\u2014" in text
        or _raw_looks_like_minor_seventh_fragment(text)
    )


def _raw_has_seventh_cue(text: str) -> bool:
    stripped = text.strip()
    return (
        "7" in stripped
        or "z" in stripped.lower()
        or stripped in {"N7", "A7"}
        or _raw_looks_like_minor_seventh_fragment(text)
    )


def _raw_looks_like_minor_seventh_fragment(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.strip()).upper()
    return compact in {"U/", "V/", "K"}


def _raw_is_rootless_minor_fragment(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.strip()).upper()
    return re.fullmatch(r"[0O][-_\u2212\u2013\u2014](?:7)?", compact) is not None


def _raw_is_standalone_extension(text: str, extension: str) -> bool:
    return text.strip() == extension


def _chord_has_major_seventh(chord: dict[str, Any]) -> bool:
    return "maj7" in str(chord.get("text_norm") or "")


def _chord_has_extension(chord: dict[str, Any], extension: str) -> bool:
    return extension in ((chord.get("components") or {}).get("extensions") or [])


def _body_from_chord(chord: dict[str, Any]) -> str | None:
    components = chord.get("components") or {}
    root = components.get("root")
    if not root:
        return None
    prefix = f"{root}{components.get('accidental') or ''}"
    main = str(chord.get("text_norm") or "").split("/", 1)[0]
    if not main.startswith(prefix):
        return None
    return main[len(prefix) :]


def _quality_from_body(body: str) -> str:
    if body.startswith("mMaj"):
        return "minor_major"
    if body.startswith("m7b5"):
        return "half_diminished"
    if body.startswith("maj"):
        return "major"
    if body.startswith("m"):
        return "minor"
    if body.startswith("dim"):
        return "diminished"
    if body.startswith("6") or body.startswith("7"):
        return "dominant" if body.startswith("7") else "major"
    return "major"


def _extensions_from_body(body: str) -> list[str]:
    return re.findall(r"(?<![#b])(?:6|7|9|11|13)", body)


def _alterations_from_body(body: str) -> list[str]:
    return re.findall(r"[#b](?:5|9|11|13)", body)


def _resolve_previous_measure_repeats(measures: list[MeasureCell]) -> None:
    previous_resolved: list[dict[str, Any]] = []
    previous_index: int | None = None
    for measure in measures:
        repeat_symbols = [
            symbol for symbol in measure.symbols if symbol.get("type") == "repeat_previous_measure"
        ]
        if repeat_symbols and previous_resolved:
            resolved = []
            for chord in previous_resolved:
                copied = {
                    key: value
                    for key, value in chord.items()
                    if key not in {"bbox", "confidence"}
                }
                copied["derived_from_measure_index"] = previous_index
                resolved.append(copied)
            for symbol in repeat_symbols:
                symbol["resolved_from_measure_index"] = previous_index
            measure.symbols.extend([])
            setattr(measure, "resolved_chords", resolved)

        if measure.chords:
            previous_resolved = measure.chords
            previous_index = measure.index
        elif hasattr(measure, "resolved_chords"):
            previous_resolved = getattr(measure, "resolved_chords")
            previous_index = measure.index


def _detect_visual_percent_repeat(
    image: np.ndarray,
    measure: MeasureCell,
) -> dict[str, Any] | None:
    if measure.chords:
        return None

    x0, y0, x1, y1 = [int(round(value)) for value in measure.bbox]
    pad_x = max(8, int((x1 - x0) * 0.04))
    pad_y = max(8, int((y1 - y0) * 0.08))
    x0 = max(0, x0 + pad_x)
    x1 = min(image.shape[1], x1 - pad_x)
    y0 = max(0, y0 + pad_y)
    y1 = min(image.shape[0], y1 - pad_y)
    if x1 <= x0 or y1 <= y0:
        return None

    crop = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )

    dot_centers: list[tuple[float, float]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 25:
            continue
        aspect = width / max(float(height), 1.0)
        fill = area / max(float(width * height), 1.0)
        if (
            8 <= width <= 80
            and 8 <= height <= 80
            and 0.55 <= aspect <= 1.45
            and fill >= 0.35
        ):
            dot_centers.append((float(x + width / 2.0), float(y + height / 2.0)))

    if len(dot_centers) < 2 or not _has_percent_diagonal(binary):
        return None

    crop_width = float(binary.shape[1])
    crop_height = float(binary.shape[0])
    upper_left_dots = [
        center for center in dot_centers if center[0] < crop_width * 0.58 and center[1] < crop_height * 0.58
    ]
    lower_right_dots = [
        center for center in dot_centers if center[0] > crop_width * 0.42 and center[1] > crop_height * 0.42
    ]
    if not upper_left_dots or not lower_right_dots:
        return None

    separated = any(
        lower[0] - upper[0] > crop_width * 0.10
        and lower[1] - upper[1] > crop_height * 0.15
        for upper in upper_left_dots
        for lower in lower_right_dots
    )
    if not separated:
        return None

    return {
        "type": "repeat_previous_measure",
        "text_raw": "%",
        "source": "visual_percent_detection",
        "measure_index": measure.index,
        "section": measure.section,
        "bbox": [float(x0), float(y0), float(x1), float(y1)],
    }


def _has_percent_diagonal(binary: np.ndarray) -> bool:
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180.0,
        threshold=28,
        minLineLength=max(32, int(min(binary.shape[:2]) * 0.28)),
        maxLineGap=14,
    )
    if lines is None:
        return False

    for line in lines[:, 0]:
        x0, y0, x1, y1 = [float(value) for value in line]
        dx = x1 - x0
        dy = y1 - y0
        if dx == 0:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        if -70.0 <= angle <= -20.0 or 110.0 <= angle <= 160.0:
            return True

    return False


def _page_payload(
    *,
    image: np.ndarray,
    rows: list[ChartRow],
    measures: list[MeasureCell],
) -> dict[str, Any]:
    measure_by_row: dict[int, list[MeasureCell]] = {}
    for measure in measures:
        measure_by_row.setdefault(measure.row_index, []).append(measure)

    systems = []
    for row in rows:
        row_measures = []
        for measure in measure_by_row.get(row.index, []):
            payload: dict[str, Any] = {
                "index": measure.index,
                "row_measure_index": measure.col_index,
                "section": measure.section,
                "bbox": [float(value) for value in measure.bbox],
                "left_boundary": {"kind": measure.left_boundary.kind},
                "right_boundary": {"kind": measure.right_boundary.kind},
                "chords": measure.chords,
                "symbols": measure.symbols,
                "navigation": measure.navigation,
            }
            if measure.ending_number is not None:
                payload["ending"] = {"number": measure.ending_number}
            if hasattr(measure, "resolved_chords"):
                payload["resolved_chords"] = getattr(measure, "resolved_chords")
            row_measures.append(payload)

        systems.append(
            {
                "index": row.index,
                "section": row.section,
                "bbox": [
                    float(row.boundaries[0].x),
                    float(row.y_top),
                    float(row.boundaries[-1].x),
                    float(row.y_bottom),
                ],
                "measures": row_measures,
            }
        )

    return {
        "page": 1,
        "width": float(image.shape[1]),
        "height": float(image.shape[0]),
        "assignment_source": "chart_grid_detection",
        "systems": systems,
    }


def _flow_payload(measures: list[MeasureCell]) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    repeat_groups = []
    navigation = []
    endings_by_number: dict[int, list[MeasureCell]] = {}
    section_start_by_name: dict[str, int] = {}
    current_repeat_start: int | None = None
    current_section: str | None = None
    current_section_start: int | None = None

    for measure in measures:
        if measure.section != current_section:
            if current_section is not None and current_section_start is not None:
                sections.append(
                    {
                        "section": current_section,
                        "start_measure_index": current_section_start,
                        "end_measure_index": measure.index - 1,
                    }
                )
            current_section = measure.section
            current_section_start = measure.index if measure.section is not None else None

        if measure.section is not None and measure.section not in section_start_by_name:
            section_start_by_name[measure.section] = measure.index

        if measure.left_boundary.kind in {"start_repeat", "repeat_both"}:
            current_repeat_start = measure.index

        if measure.ending_number is not None:
            endings_by_number.setdefault(measure.ending_number, []).append(measure)

        if measure.right_boundary.kind in {"end_repeat", "repeat_both"}:
            repeat_groups.append(
                {
                    "start_measure_index": current_repeat_start
                    or (
                        section_start_by_name.get(measure.section)
                        if measure.section is not None
                        else 1
                    ),
                    "end_measure_index": measure.index,
                    "section": measure.section,
                }
            )
            current_repeat_start = None

        navigation.extend(measure.navigation)

    if current_section is not None and current_section_start is not None and measures:
        sections.append(
            {
                "section": current_section,
                "start_measure_index": current_section_start,
                "end_measure_index": measures[-1].index,
            }
        )

    endings = []
    for number, ending_measures in sorted(endings_by_number.items()):
        endings.append(
            {
                "number": number,
                "start_measure_index": ending_measures[0].index,
                "end_measure_index": ending_measures[-1].index,
                "section": ending_measures[0].section,
            }
        )

    return {
        "sections": sections,
        "repeat_groups": repeat_groups,
        "endings": endings,
        "navigation": navigation,
    }


def _join_tokens_same_line(tokens: list[OCRToken]) -> str | None:
    if not tokens:
        return None
    ordered = sorted(tokens, key=lambda item: item.cx)
    return " ".join(token.text.strip() for token in ordered if token.text.strip()) or None


def _clean_wrapped_text(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        return cleaned[1:-1].strip()
    return cleaned


def _average_confidence(tokens: list[OCRToken]) -> float | None:
    values = [token.confidence for token in tokens if token.confidence is not None]
    if not values:
        return None
    return float(sum(values) / len(values))
