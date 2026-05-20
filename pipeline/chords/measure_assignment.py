from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from pipeline.chords.fallback_barlines import detect_barlines_cv
from pipeline.chords.models import (
    BBox,
    ChordToken,
    Measure,
    MeasureChord,
    SystemRow,
    bbox_center,
    median,
    merge_close_values,
    quantize_beat,
)

MIN_MEASURE_WIDTH = 12.0


@dataclass(frozen=True)
class SeparatorCandidate:
    center_x: float
    width: int
    height: int
    area: int


def assign_chords_to_measures(
    *,
    tokens: list[ChordToken],
    geometry: dict[str, Any] | None,
    image: np.ndarray,
    source_path: str,
    time_signature: str = "4/4",
    beats_per_bar: int = 4,
    expected_measure_counts_by_system: list[int] | None = None,
) -> dict[str, Any]:
    if _geometry_is_usable_for_tokens(geometry, tokens):
        page = _build_from_homr_geometry(
            tokens=tokens,
            geometry=geometry,
            image=image,
            beats_per_bar=beats_per_bar,
            expected_measure_counts_by_system=expected_measure_counts_by_system,
        )
    else:
        page = _build_from_cv_fallback(
            tokens=tokens,
            image=image,
            beats_per_bar=beats_per_bar,
        )

    return {
        "source": source_path,
        "time_signature": time_signature,
        "beats_per_bar": beats_per_bar,
        "pages": [page],
    }


def _geometry_is_usable_for_tokens(
    geometry: dict[str, Any] | None,
    tokens: list[ChordToken],
) -> bool:
    if not geometry:
        return False
    if geometry.get("coordinate_space") != "homr_processed_image":
        return False

    image = geometry.get("image") or {}
    systems = geometry.get("systems") or []
    barlines = geometry.get("barlines") or []
    if image.get("width", 0) <= 0 or image.get("height", 0) <= 0:
        return False
    if not systems or not barlines:
        return False

    system_rows = _systems_from_geometry(systems)
    if not system_rows:
        return False

    barline_xs = [_barline_x_positions_for_system(system, barlines) for system in system_rows]
    if not tokens:
        return any(len(xs) >= 2 for xs in barline_xs)

    tokens_by_system = _tokens_by_nearest_system(tokens, system_rows)
    for system_index, system_tokens in enumerate(tokens_by_system):
        if system_tokens and len(barline_xs[system_index]) < 2:
            return False

    return any(tokens_by_system)


def _build_from_homr_geometry(
    *,
    tokens: list[ChordToken],
    geometry: dict[str, Any],
    image: np.ndarray,
    beats_per_bar: int,
    expected_measure_counts_by_system: list[int] | None,
) -> dict[str, Any]:
    systems = _systems_from_geometry(geometry["systems"])
    tokens_by_system = _tokens_by_nearest_system(tokens, systems)
    next_measure_index = 1

    for system_index, (system, system_tokens) in enumerate(
        zip(systems, tokens_by_system, strict=True),
    ):
        barline_positions = _barline_x_positions_for_system(system, geometry["barlines"])
        boundaries = _include_leading_system_boundary_if_needed(
            system=system,
            barline_positions=barline_positions,
        )
        expected_measure_count = None
        if (
            expected_measure_counts_by_system is not None
            and system_index < len(expected_measure_counts_by_system)
        ):
            expected_measure_count = expected_measure_counts_by_system[system_index]
        boundaries = _recover_missing_barlines_from_image(
            system=system,
            boundaries=boundaries,
            image=image,
            expected_measure_count=expected_measure_count,
        )
        measures, next_measure_index = _build_measures_from_boundaries(
            system=system,
            boundaries=boundaries,
            next_measure_index=next_measure_index,
        )
        system.measures = measures
        _assign_tokens_to_measures(
            tokens=system_tokens,
            measures=system.measures,
            beats_per_bar=beats_per_bar,
        )

    return _serialize_page(
        width=float(geometry["image"]["width"]),
        height=float(geometry["image"]["height"]),
        systems=systems,
        assignment_source="homr_geometry",
    )


def _build_from_cv_fallback(
    *,
    tokens: list[ChordToken],
    image: np.ndarray,
    beats_per_bar: int,
) -> dict[str, Any]:
    height, width = image.shape[:2]
    barlines, _debug_mask = detect_barlines_cv(image)
    systems = _cluster_tokens_into_rows(tokens)
    per_system_barlines = _assign_fallback_barlines_to_rows(systems, barlines)
    tokens_by_system = _tokens_by_nearest_system(tokens, systems)
    next_measure_index = 1

    for system_index, system in enumerate(systems):
        boundaries = per_system_barlines[system_index]
        if len(boundaries) < 2:
            boundaries = _fallback_boundaries_from_tokens(
                tokens_by_system[system_index],
                page_width=float(width),
            )

        measures, next_measure_index = _build_measures_from_boundaries(
            system=system,
            boundaries=boundaries,
            next_measure_index=next_measure_index,
        )
        system.measures = measures
        _assign_tokens_to_measures(
            tokens=tokens_by_system[system_index],
            measures=system.measures,
            beats_per_bar=beats_per_bar,
        )

    return _serialize_page(
        width=float(width),
        height=float(height),
        systems=systems,
        assignment_source="cv_fallback",
    )


def _systems_from_geometry(raw_systems: list[dict[str, Any]]) -> list[SystemRow]:
    systems: list[SystemRow] = []
    for raw_system in raw_systems:
        bbox = _coerce_bbox(raw_system.get("bbox"))
        if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        systems.append(
            SystemRow(
                index=int(raw_system.get("index", len(systems) + 1)),
                y_center=(bbox[1] + bbox[3]) / 2.0,
                y_top=bbox[1],
                y_bottom=bbox[3],
                bbox=bbox,
                measures=[],
            )
        )

    systems.sort(key=lambda system: system.y_center)
    for index, system in enumerate(systems, start=1):
        system.index = index
    return systems


def _barline_x_positions_for_system(
    system: SystemRow,
    raw_barlines: list[dict[str, Any]],
) -> list[float]:
    positions: list[float] = []
    for raw_barline in raw_barlines:
        bbox = _coerce_bbox(raw_barline.get("bbox"))
        if bbox is None:
            continue
        if bbox[1] <= system.y_bottom and bbox[3] >= system.y_top:
            center = raw_barline.get("center")
            if isinstance(center, list | tuple) and len(center) >= 1:
                positions.append(float(center[0]))
            else:
                positions.append((bbox[0] + bbox[2]) / 2.0)
    return sorted(merge_close_values(positions, tol=2.0))


def _tokens_by_nearest_system(
    tokens: list[ChordToken],
    systems: list[SystemRow],
) -> list[list[ChordToken]]:
    grouped_tokens: list[list[ChordToken]] = [[] for _ in systems]
    if not systems:
        return grouped_tokens

    for token in tokens:
        best_index = min(
            range(len(systems)),
            key=lambda index: abs(token.cy - systems[index].y_center),
        )
        grouped_tokens[best_index].append(token)

    for grouped in grouped_tokens:
        grouped.sort(key=lambda token: (token.cx, token.cy))
    return grouped_tokens


def _build_measures_from_boundaries(
    *,
    system: SystemRow,
    boundaries: list[float],
    next_measure_index: int,
) -> tuple[list[Measure], int]:
    merged_boundaries = sorted(merge_close_values(boundaries, tol=1.0))
    measures: list[Measure] = []

    for column_index in range(len(merged_boundaries) - 1):
        left = merged_boundaries[column_index]
        right = merged_boundaries[column_index + 1]
        if right - left < MIN_MEASURE_WIDTH:
            continue
        measures.append(
            Measure(
                index=next_measure_index,
                row_index=system.index,
                col_index=len(measures) + 1,
                bbox=(left, system.y_top, right, system.y_bottom),
                chords=[],
            )
        )
        next_measure_index += 1

    if measures:
        system.bbox = (
            measures[0].bbox[0],
            system.y_top,
            measures[-1].bbox[2],
            system.y_bottom,
        )
    return measures, next_measure_index


def _assign_tokens_to_measures(
    *,
    tokens: list[ChordToken],
    measures: list[Measure],
    beats_per_bar: int,
) -> None:
    if not measures:
        return

    for token in tokens:
        center_x, _center_y = bbox_center(token.bbox)
        target = next(
            (
                measure
                for measure in measures
                if measure.bbox[0] <= center_x <= measure.bbox[2]
            ),
            None,
        )
        if target is None:
            target = measures[0] if center_x < measures[0].bbox[0] else measures[-1]

        target.chords.append(
            MeasureChord(
                text_raw=token.text_raw,
                text_norm=token.text_norm,
                bbox=token.bbox,
                beat=quantize_beat(
                    center_x,
                    target.bbox[0],
                    target.bbox[2],
                    beats_per_bar,
                ),
            )
        )

    for measure in measures:
        measure.chords.sort(key=lambda chord: (chord.bbox[0], chord.bbox[1]))


def _include_leading_system_boundary_if_needed(
    *,
    system: SystemRow,
    barline_positions: list[float],
) -> list[float]:
    """
    HOMR barlines describe visual separators, but the left edge of a system is
    also the leading boundary of its first measure. If the first detected
    barline sits a full measure-width away from the system envelope, preserve
    that leading interval instead of silently dropping measure 1.

    Small gaps are treated as geometry jitter around a real left barline rather
    than as a separate measure.
    """
    if not barline_positions:
        return []

    boundaries = sorted(merge_close_values(barline_positions, tol=1.0))
    leading_gap = boundaries[0] - system.bbox[0]
    substantial_gaps = [
        right - left
        for left, right in zip(boundaries, boundaries[1:])
        if right - left >= MIN_MEASURE_WIDTH
    ]
    typical_measure_width = median(substantial_gaps)
    min_leading_gap = max(
        MIN_MEASURE_WIDTH * 2.0,
        typical_measure_width * 0.25 if typical_measure_width else 0.0,
    )

    if leading_gap >= min_leading_gap:
        return [system.bbox[0], *boundaries]
    return boundaries


def _recover_missing_barlines_from_image(
    *,
    system: SystemRow,
    boundaries: list[float],
    image: np.ndarray,
    expected_measure_count: int | None = None,
) -> list[float]:
    """
    Recover an occasional missed HOMR barline from the aligned processed image.

    This is intentionally conservative: only inspect intervals that are much
    wider than the surrounding measure widths, or intervals in systems where
    MusicXML says one more measure should exist. In both cases a split still
    requires a narrow/tall vertical separator in the image.
    """
    boundaries = sorted(merge_close_values(boundaries, tol=1.0))
    substantial_gaps = [
        right - left
        for left, right in zip(boundaries, boundaries[1:])
        if right - left >= MIN_MEASURE_WIDTH
    ]
    typical_measure_width = median(substantial_gaps)
    if typical_measure_width <= 0:
        return boundaries

    expected_deficit = 0
    current_measure_count = max(0, len(boundaries) - 1)
    if expected_measure_count is not None:
        expected_deficit = max(0, expected_measure_count - current_measure_count)

    recovery_candidates: list[
        tuple[tuple[float, float, float], float, SeparatorCandidate]
    ] = []
    for left, right in zip(boundaries, boundaries[1:]):
        gap = right - left
        if not _should_inspect_interval(
            gap=gap,
            typical_measure_width=typical_measure_width,
            expected_deficit=expected_deficit,
        ):
            continue

        vertical_candidates = _vertical_separator_candidates(
            image=image,
            system=system,
            left=left,
            right=right,
        )
        if not vertical_candidates:
            continue

        best_candidate = min(
            vertical_candidates,
            key=lambda candidate: _candidate_split_score(
                candidate=candidate,
                left=left,
                right=right,
                typical_measure_width=typical_measure_width,
            )
        )
        score = _candidate_split_score(
            candidate=best_candidate,
            left=left,
            right=right,
            typical_measure_width=typical_measure_width,
        )
        recovery_candidates.append((score, best_candidate.center_x, best_candidate))

    if expected_deficit > 0:
        recovered_positions = [
            candidate.center_x
            for _score, _center_x, candidate in sorted(recovery_candidates)[
                :expected_deficit
            ]
        ]
    else:
        recovered_positions = [
            candidate.center_x for _score, _center_x, candidate in recovery_candidates
        ]

    return sorted(merge_close_values([*boundaries, *recovered_positions], tol=1.0))


def _should_inspect_interval(
    *,
    gap: float,
    typical_measure_width: float,
    expected_deficit: int,
) -> bool:
    if gap < MIN_MEASURE_WIDTH * 2.0:
        return False

    if expected_deficit > 0:
        return typical_measure_width * 1.25 <= gap <= typical_measure_width * 2.75

    return typical_measure_width * 1.6 <= gap <= typical_measure_width * 2.5


def _candidate_split_score(
    *,
    candidate: SeparatorCandidate,
    left: float,
    right: float,
    typical_measure_width: float,
) -> tuple[float, float, float]:
    balance_score = (
        abs((candidate.center_x - left) - typical_measure_width)
        + abs((right - candidate.center_x) - typical_measure_width)
    )
    strength_bonus = min(float(candidate.area), 500.0) * 0.25
    midpoint_distance = abs(candidate.center_x - ((left + right) / 2.0))
    return (balance_score - strength_bonus, balance_score, midpoint_distance)


def _vertical_separator_candidates(
    *,
    image: np.ndarray,
    system: SystemRow,
    left: float,
    right: float,
) -> list[SeparatorCandidate]:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    y0 = max(0, int(round(system.y_top)))
    y1 = min(gray.shape[0], int(round(system.y_bottom)) + 1)
    x0 = max(0, int(round(left)))
    x1 = min(gray.shape[1], int(round(right)) + 1)
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return []

    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    minimum_height = max(3, int(round(roi.shape[0] * 0.75)))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, minimum_height))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

    label_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        (vertical > 0).astype(np.uint8),
        8,
    )
    candidates: list[SeparatorCandidate] = []
    margin = MIN_MEASURE_WIDTH * 2.0

    for label in range(1, label_count):
        x, _y, width, height, _area = [int(value) for value in stats[label]]
        if height < minimum_height or width > MIN_MEASURE_WIDTH:
            continue

        center_x = float(x0 + x + (width - 1) / 2.0)
        if center_x - left < margin or right - center_x < margin:
            continue
        candidates.append(
            SeparatorCandidate(
                center_x=center_x,
                width=width,
                height=height,
                area=_area,
            )
        )

    return candidates


def _cluster_tokens_into_rows(tokens: list[ChordToken]) -> list[SystemRow]:
    if not tokens:
        return []

    groups: list[list[ChordToken]] = []
    for token in sorted(tokens, key=lambda current: current.cy):
        for group in groups:
            if abs(group[0].cy - token.cy) <= 28.0:
                group.append(token)
                break
        else:
            groups.append([token])

    systems: list[SystemRow] = []
    for index, group in enumerate(groups, start=1):
        y_center = median([token.cy for token in group])
        y_top = min(token.bbox[1] for token in group) - 18.0
        y_bottom = max(token.bbox[3] for token in group) + 120.0
        bbox = (
            min(token.bbox[0] for token in group),
            y_top,
            max(token.bbox[2] for token in group),
            y_bottom,
        )
        systems.append(
            SystemRow(
                index=index,
                y_center=y_center,
                y_top=y_top,
                y_bottom=y_bottom,
                bbox=bbox,
                measures=[],
            )
        )

    return systems


def _assign_fallback_barlines_to_rows(
    systems: list[SystemRow],
    barlines: list[tuple[float, float, float]],
) -> list[list[float]]:
    per_system_positions: list[list[float]] = [[] for _ in systems]
    for x, top, bottom in barlines:
        for index, system in enumerate(systems):
            if top <= system.y_bottom and bottom >= system.y_top:
                per_system_positions[index].append(x)

    return [
        sorted(merge_close_values(positions, tol=2.0))
        for positions in per_system_positions
    ]


def _fallback_boundaries_from_tokens(
    tokens: list[ChordToken],
    *,
    page_width: float,
) -> list[float]:
    if not tokens:
        return []

    left = max(0.0, min(token.bbox[0] for token in tokens) - 20.0)
    right = min(page_width, max(token.bbox[2] for token in tokens) + 20.0)
    return [left, right]


def _serialize_page(
    *,
    width: float,
    height: float,
    systems: list[SystemRow],
    assignment_source: str,
) -> dict[str, Any]:
    return {
        "page": 1,
        "width": width,
        "height": height,
        "assignment_source": assignment_source,
        "systems": [
            {
                "index": system.index,
                "bbox": list(system.bbox),
                "measures": [
                    {
                        "index": measure.index,
                        "row_index": measure.row_index,
                        "col_index": measure.col_index,
                        "bbox": list(measure.bbox),
                        "chords": [
                            {
                                "text_raw": chord.text_raw,
                                "text_norm": chord.text_norm,
                                "bbox": list(chord.bbox),
                                "beat": chord.beat,
                            }
                            for chord in measure.chords
                        ],
                    }
                    for measure in system.measures
                ],
            }
            for system in systems
        ],
    }


def _coerce_bbox(value: Any) -> BBox | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None

    try:
        return tuple(float(component) for component in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None
