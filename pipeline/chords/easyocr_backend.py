from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from pipeline.chords.grammar import looks_like_chord_ocr, normalize_text
from pipeline.chords.models import ChordToken, merge_close_values
from pipeline.chords.ocr_common import preprocess_for_ocr, try_split_merged_token


_reader: Any | None = None
_MIN_TARGETED_SYSTEM_COVERAGE = 0.50
_MIN_TARGETED_SYSTEMS_WITH_CHORDS = 0.25
_MIN_TARGETED_TOKENS_PER_MEASURE = 0.20


@dataclass(frozen=True)
class OCRRegion:
    source: str
    system_index: int
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class OCRPassResult:
    tokens: list[ChordToken]
    rejects: list[dict[str, Any]]


def _get_reader(*, gpu: bool = False) -> Any:
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(["en"], gpu=gpu)
    return _reader


def extract_chord_tokens_ocr(
    image: np.ndarray,
    *,
    geometry: dict[str, Any] | None = None,
    min_confidence: float = 0.15,
    gpu: bool = False,
    ocr_scale: float = 2.0,
    use_targeted_regions: bool = True,
    return_strategy: bool = False,
) -> tuple[list[ChordToken], list[dict[str, Any]]] | tuple[
    list[ChordToken],
    list[dict[str, Any]],
    dict[str, Any],
]:
    if use_targeted_regions and geometry is not None:
        result, strategy = _extract_with_targeted_regions(
            image=image,
            geometry=geometry,
            min_confidence=min_confidence,
            gpu=gpu,
            ocr_scale=ocr_scale,
        )
    else:
        result = _run_ocr_pass(
            image,
            min_confidence=min_confidence,
            gpu=gpu,
            ocr_scale=ocr_scale,
            source="full_page",
        )
        strategy = {
            "mode": "full_page",
            "targeted": {
                "attempted": False,
                "reason": "no_geometry" if geometry is None else "disabled",
            },
            "fallback": {"triggered": False, "reason": None},
        }

    result.tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    if return_strategy:
        return result.tokens, result.rejects, strategy

    return result.tokens, result.rejects


def _extract_with_targeted_regions(
    *,
    image: np.ndarray,
    geometry: dict[str, Any],
    min_confidence: float,
    gpu: bool,
    ocr_scale: float,
) -> tuple[OCRPassResult, dict[str, Any]]:
    systems = _usable_systems(geometry)
    regions = _chord_band_regions(image=image, geometry=geometry, systems=systems)
    estimated_visual_measures = _estimate_visual_measure_count(
        geometry=geometry,
        systems=systems,
    )
    targeted_strategy: dict[str, Any] = {
        "attempted": True,
        "regions": len(regions),
        "systems_total": len(systems),
        "usable_system_crop_count": len({region.system_index for region in regions}),
        "estimated_visual_measures": estimated_visual_measures,
    }

    if not regions:
        full_page_result = _run_ocr_pass(
            image,
            min_confidence=min_confidence,
            gpu=gpu,
            ocr_scale=ocr_scale,
            source="full_page",
        )
        strategy = {
            "mode": "full_page",
            "targeted": {
                **targeted_strategy,
                "reason": "no_usable_target_regions",
            },
            "fallback": {
                "triggered": True,
                "reason": "no_usable_target_regions",
                "accepted_tokens_before_visual_filters": len(full_page_result.tokens),
            },
        }
        return full_page_result, strategy

    targeted_result = OCRPassResult(tokens=[], rejects=[])
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        crop = image[y0:y1, x0:x1]
        region_result = _run_ocr_pass(
            crop,
            min_confidence=min_confidence,
            gpu=gpu,
            ocr_scale=ocr_scale,
            source=region.source,
            offset=(x0, y0),
            system_index=region.system_index,
        )
        targeted_result.tokens.extend(region_result.tokens)
        targeted_result.rejects.extend(region_result.rejects)

    systems_with_chords = _systems_with_tokens(targeted_result.tokens, systems)
    targeted_strategy.update(
        {
            "accepted_tokens_before_visual_filters": len(targeted_result.tokens),
            "rejected_hits": len(targeted_result.rejects),
            "systems_with_chords": len(systems_with_chords),
        }
    )
    fallback_reason = _targeted_fallback_reason(
        targeted_tokens=targeted_result.tokens,
        systems_total=len(systems),
        usable_system_crop_count=targeted_strategy["usable_system_crop_count"],
        systems_with_chords=len(systems_with_chords),
        estimated_visual_measures=estimated_visual_measures,
    )

    if fallback_reason is None:
        strategy = {
            "mode": "targeted_only",
            "targeted": targeted_strategy,
            "fallback": {"triggered": False, "reason": None},
        }
        return targeted_result, strategy

    full_page_result = _run_ocr_pass(
        image,
        min_confidence=min_confidence,
        gpu=gpu,
        ocr_scale=ocr_scale,
        source="full_page",
    )
    merged_tokens = _merge_ocr_tokens([*targeted_result.tokens, *full_page_result.tokens])
    strategy = {
        "mode": "targeted_with_full_page_fallback",
        "targeted": targeted_strategy,
        "fallback": {
            "triggered": True,
            "reason": fallback_reason,
            "accepted_tokens_before_visual_filters": len(full_page_result.tokens),
            "merged_tokens_before_visual_filters": len(merged_tokens),
        },
    }
    return (
        OCRPassResult(
            tokens=merged_tokens,
            rejects=[*targeted_result.rejects, *full_page_result.rejects],
        ),
        strategy,
    )


def _run_ocr_pass(
    image: np.ndarray,
    *,
    min_confidence: float,
    gpu: bool,
    ocr_scale: float,
    source: str,
    offset: tuple[float, float] = (0.0, 0.0),
    system_index: int | None = None,
) -> OCRPassResult:
    processed = preprocess_for_ocr(image, scale=ocr_scale)
    reader = _get_reader(gpu=gpu)
    results = _readtext(reader, processed)
    inverse_scale = 1.0 / ocr_scale
    offset_x, offset_y = offset

    tokens: list[ChordToken] = []
    rejects: list[dict[str, Any]] = []

    for points, text, confidence in results:
        raw_text = (text or "").strip()
        if not raw_text:
            continue
        confidence_value = float(confidence)

        xs = [offset_x + point[0] * inverse_scale for point in points]
        ys = [offset_y + point[1] * inverse_scale for point in points]
        bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))

        if confidence_value < min_confidence:
            rejects.append(
                {
                    "text": raw_text,
                    "bbox": list(bbox),
                    "conf": confidence_value,
                    "source": source,
                    **(
                        {"system_index": system_index}
                        if system_index is not None
                        else {}
                    ),
                    "reason": (
                        f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                    ),
                }
            )
            continue

        passed, corrected = looks_like_chord_ocr(raw_text)
        if passed:
            tokens.append(
                ChordToken(
                    text_raw=raw_text,
                    text_norm=normalize_text(corrected),
                    bbox=bbox,
                    confidence=confidence_value,
                )
            )
            continue

        split_tokens = try_split_merged_token(
            raw_text,
            bbox,
            confidence=confidence_value,
        )
        if split_tokens:
            tokens.extend(split_tokens)
            continue

        rejects.append(
            {
                "text": raw_text,
                "text_norm": corrected,
                "bbox": list(bbox),
                "conf": confidence_value,
                "source": source,
                **(
                    {"system_index": system_index}
                    if system_index is not None
                    else {}
                ),
                "reason": "failed chord grammar",
            }
        )

    return OCRPassResult(tokens=tokens, rejects=rejects)


def _readtext(reader: Any, image: np.ndarray) -> list[Any]:
    return reader.readtext(image, detail=1, paragraph=False)


def _usable_systems(
    geometry: dict[str, Any],
) -> list[tuple[int, tuple[float, float, float, float]]]:
    if geometry.get("coordinate_space") != "homr_processed_image":
        return []

    systems: list[tuple[int, tuple[float, float, float, float]]] = []
    for raw_system in geometry.get("systems") or []:
        bbox = _coerce_bbox(raw_system.get("bbox"))
        if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        systems.append((int(raw_system.get("index", len(systems) + 1)), bbox))

    systems.sort(key=lambda item: ((item[1][1] + item[1][3]) / 2.0, item[1][0]))
    return systems


def _chord_band_regions(
    *,
    image: np.ndarray,
    geometry: dict[str, Any],
    systems: list[tuple[int, tuple[float, float, float, float]]] | None = None,
) -> list[OCRRegion]:
    height, width = image.shape[:2]
    usable_systems = systems if systems is not None else _usable_systems(geometry)
    regions: list[OCRRegion] = []

    for system_index, bbox in usable_systems:
        x0, y0, x1, y1 = bbox
        system_height = max(1.0, y1 - y0)
        system_width = max(1.0, x1 - x0)
        x_margin = max(12.0, min(48.0, system_width * 0.04))
        top_margin = max(60.0, min(180.0, system_height * 1.45))
        staff_overlap = min(8.0, system_height * 0.08)

        crop_x0 = int(max(0, round(x0 - x_margin)))
        crop_x1 = int(min(width, round(x1 + x_margin)))
        crop_y0 = int(max(0, round(y0 - top_margin)))
        crop_y1 = int(min(height, round(y0 + staff_overlap)))

        if crop_x1 - crop_x0 < 24 or crop_y1 - crop_y0 < 20:
            continue
        regions.append(
            OCRRegion(
                source="targeted_chord_band",
                system_index=system_index,
                bbox=(crop_x0, crop_y0, crop_x1, crop_y1),
            )
        )

    return regions


def _targeted_fallback_reason(
    *,
    targeted_tokens: list[ChordToken],
    systems_total: int,
    usable_system_crop_count: int,
    systems_with_chords: int,
    estimated_visual_measures: int,
) -> str | None:
    if systems_total <= 0:
        return "no_usable_system_geometry"

    if usable_system_crop_count / systems_total < _MIN_TARGETED_SYSTEM_COVERAGE:
        return "insufficient_target_region_coverage"

    if not targeted_tokens:
        return "no_targeted_chord_tokens"

    if systems_with_chords / systems_total < _MIN_TARGETED_SYSTEMS_WITH_CHORDS:
        return "too_few_systems_with_chords"

    if (
        estimated_visual_measures > 0
        and len(targeted_tokens) / estimated_visual_measures
        < _MIN_TARGETED_TOKENS_PER_MEASURE
    ):
        return "too_few_chord_tokens_per_measure"

    return None


def _systems_with_tokens(
    tokens: list[ChordToken],
    systems: list[tuple[int, tuple[float, float, float, float]]],
) -> set[int]:
    result: set[int] = set()
    if not systems:
        return result

    for token in tokens:
        system_index, _bbox = min(
            systems,
            key=lambda item: abs(token.cy - item[1][1]),
        )
        result.add(system_index)
    return result


def _estimate_visual_measure_count(
    *,
    geometry: dict[str, Any],
    systems: list[tuple[int, tuple[float, float, float, float]]],
) -> int:
    barline_records = []
    for raw_barline in geometry.get("barlines") or []:
        bbox = _coerce_bbox(raw_barline.get("bbox"))
        if bbox is None:
            continue
        barline_records.append((_barline_center_x(raw_barline, bbox), bbox))

    measure_count = 0
    for _system_index, system_bbox in systems:
        system_x0, system_y0, _system_x1, system_y1 = system_bbox
        positions = [
            center_x
            for center_x, bbox in barline_records
            if bbox[1] <= system_y1 and bbox[3] >= system_y0
        ]
        positions = sorted(merge_close_values(positions, tol=2.0))
        if len(positions) < 2:
            continue

        system_measure_count = len(positions) - 1
        leading_gap = positions[0] - system_x0
        median_gap = _median_gap(positions)
        if leading_gap >= max(24.0, median_gap * 0.25):
            system_measure_count += 1
        measure_count += max(0, system_measure_count)

    return measure_count


def _barline_center_x(
    raw_barline: dict[str, Any],
    bbox: tuple[float, float, float, float] | None,
) -> float:
    center = raw_barline.get("center")
    if isinstance(center, list | tuple) and center:
        return float(center[0])
    if bbox is None:
        return 0.0
    return (bbox[0] + bbox[2]) / 2.0


def _median_gap(positions: list[float]) -> float:
    gaps = [
        right - left
        for left, right in zip(positions, positions[1:])
        if right - left > 0
    ]
    if not gaps:
        return 0.0
    return sorted(gaps)[len(gaps) // 2]


def _merge_ocr_tokens(tokens: list[ChordToken]) -> list[ChordToken]:
    merged: list[ChordToken] = []
    for token in sorted(tokens, key=lambda current: (current.bbox[1], current.bbox[0])):
        duplicate_index = _matching_token_index(token, merged)
        if duplicate_index is None:
            merged.append(token)
            continue

        current = merged[duplicate_index]
        if (token.confidence or 0.0) > (current.confidence or 0.0):
            merged[duplicate_index] = token

    return merged


def _matching_token_index(token: ChordToken, candidates: list[ChordToken]) -> int | None:
    for index, current in enumerate(candidates):
        if token.text_norm != current.text_norm:
            continue
        if _bbox_iou(token.bbox, current.bbox) >= 0.35:
            return index
        if abs(token.cx - current.cx) <= 8.0 and abs(token.cy - current.cy) <= 8.0:
            return index
    return None


def _bbox_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0

    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _coerce_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        return tuple(float(component) for component in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None
