from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from pipeline.chord_charts.visual_suffix import normalize_suffix_ocr_text
from pipeline.chords.easyocr_backend import _get_reader
from pipeline.chords.ocr_common import preprocess_for_ocr


CORE_SEMANTIC_CHART_CELL_REGION_NAMES = (
    "root",
    "root_accidental",
    "suffix_lower_right",
)
MULTI_CHORD_CHART_CELL_REGION_NAMES = (
    "root_anchor_scan",
)
SEMANTIC_CHART_CELL_REGION_NAMES = CORE_SEMANTIC_CHART_CELL_REGION_NAMES
CHART_ROOT_OCR_ALLOWLIST = "ABCDEFG"
CHART_ACCIDENTAL_OCR_ALLOWLIST = (
    "b#vVhHpPnN6"
    "\u266d\u266f\ue260\ue262\ue10d\ue10c"
)
CHART_WIDE_ACCIDENTAL_OCR_ALLOWLIST = "bB#\u266d\u266f\ue260\ue262\ue10d\ue10c"
CHART_SUFFIX_OCR_ALLOWLIST = (
    "ABCDEFGabcdefgijlnorstuxmM0123456789#b()/+-_ "
    "\u00b0\u00f8\u25b3\u2206\u0394\ue260\ue262\ue10d\ue10c"
)
CHART_SEMANTIC_REGION_ALLOWLISTS = {
    "root": CHART_ROOT_OCR_ALLOWLIST,
    "root_accidental": CHART_ACCIDENTAL_OCR_ALLOWLIST,
    "suffix_lower_right": CHART_SUFFIX_OCR_ALLOWLIST,
    "root_anchor_scan": CHART_ROOT_OCR_ALLOWLIST,
    "root_wide": CHART_ROOT_OCR_ALLOWLIST,
    "root_accidental_wide": CHART_WIDE_ACCIDENTAL_OCR_ALLOWLIST,
    "suffix_wide": CHART_SUFFIX_OCR_ALLOWLIST,
}


@dataclass(frozen=True)
class OCRToken:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None = None
    source: str = "page_ocr"
    row_index: int | None = None
    col_index: int | None = None
    measure_index: int | None = None
    region: str | None = None
    debug: dict[str, Any] | None = None

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": self.text,
            "bbox": [float(value) for value in self.bbox],
            "confidence": self.confidence,
            "source": self.source,
        }
        if self.row_index is not None:
            payload["row_index"] = self.row_index
        if self.col_index is not None:
            payload["col_index"] = self.col_index
        if self.measure_index is not None:
            payload["measure_index"] = self.measure_index
        if self.region is not None:
            payload["region"] = self.region
        if self.debug is not None:
            payload["debug"] = self.debug
        return payload


@dataclass(frozen=True)
class RootAnchorCandidate:
    measure_index: int
    anchor_index: int
    root: str
    center_x: float
    bbox: tuple[float, float, float, float]
    confidence: float | None
    source_text: str
    source_bbox: tuple[float, float, float, float]
    row_index: int | None = None
    col_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "measure_index": self.measure_index,
            "anchor_index": self.anchor_index,
            "root": self.root,
            "center_x": self.center_x,
            "bbox": [float(value) for value in self.bbox],
            "confidence": self.confidence,
            "source_text": self.source_text,
            "source_bbox": [float(value) for value in self.source_bbox],
            "row_index": self.row_index,
            "col_index": self.col_index,
        }


def extract_chart_ocr_tokens(
    image: np.ndarray,
    *,
    min_confidence: float = 0.10,
    gpu: bool = False,
    ocr_scale: float = 2.0,
) -> tuple[list[OCRToken], list[dict[str, Any]]]:
    processed = preprocess_for_ocr(image, scale=ocr_scale)
    reader = _get_reader(gpu=gpu)
    results = _read_chart_text(reader, processed)
    inverse_scale = 1.0 / ocr_scale

    tokens: list[OCRToken] = []
    rejects: list[dict[str, Any]] = []

    for points, text, confidence in results:
        raw_text = (text or "").strip()
        if not raw_text:
            continue

        confidence_value = float(confidence)
        xs = [point[0] * inverse_scale for point in points]
        ys = [point[1] * inverse_scale for point in points]
        bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))

        if confidence_value < min_confidence:
            rejects.append(
                {
                    "text": raw_text,
                    "bbox": list(bbox),
                    "confidence": confidence_value,
                    "reason": (
                        f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                    ),
                }
            )
            continue

        tokens.append(
            OCRToken(
                text=raw_text,
                bbox=bbox,
                confidence=confidence_value,
                source="page_ocr",
            )
        )

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects


def extract_chart_cell_ocr_tokens(
    image: np.ndarray,
    rows: list[Any],
    *,
    min_confidence: float = 0.05,
    gpu: bool = False,
    ocr_scale: float = 2.0,
    measure_indices: set[int] | None = None,
    region_names: tuple[str, ...] | None = None,
    region_allowlists: dict[str, str] | None = None,
    source: str = "cell_ocr",
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[list[OCRToken], list[dict[str, Any]]]:
    reader = _get_reader(gpu=gpu)
    tokens: list[OCRToken] = []
    rejects: list[dict[str, Any]] = []

    row_list = list(rows)
    selected_regions = _selected_cell_ocr_regions(region_names)
    total_regions = _count_cell_ocr_regions(
        row_list,
        measure_indices=measure_indices,
        region_names=region_names,
    )
    completed_regions = 0
    measure_index = 1
    for row_position, row in enumerate(row_list):
        boundaries = getattr(row, "boundaries", [])
        for col_index, (left, right) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            if measure_indices is not None and measure_index not in measure_indices:
                measure_index += 1
                continue

            x0 = int(max(0, float(left.x) + 8))
            x1 = int(min(image.shape[1], float(right.x) - 8))
            next_y_top = (
                float(getattr(row_list[row_position + 1], "y_top"))
                if row_position + 1 < len(row_list)
                else float(image.shape[0])
            )
            y0 = int(max(0, float(row.y_top) - 35))
            y1 = int(min(image.shape[0], next_y_top - 8, float(row.y_bottom) + 80))
            if x1 <= x0 or y1 <= y0:
                completed_regions += len(selected_regions)
                _report_cell_ocr_progress(
                    progress_callback,
                    completed=completed_regions,
                    total=total_regions,
                )
                measure_index += 1
                continue

            crop = image[y0:y1, x0:x1].copy()
            for region_name, xa, xb, ya, yb in selected_regions:
                crop_height, crop_width = crop.shape[:2]
                rx0 = int(crop_width * xa)
                rx1 = int(crop_width * xb)
                ry0 = int(crop_height * ya)
                ry1 = int(crop_height * yb)
                subcrop = crop[ry0:ry1, rx0:rx1]
                if subcrop.size == 0:
                    completed_regions += 1
                    _report_cell_ocr_progress(
                        progress_callback,
                        completed=completed_regions,
                        total=total_regions,
                    )
                    continue

                processed = preprocess_for_ocr(subcrop, scale=ocr_scale)
                inverse_scale = 1.0 / ocr_scale
                results = _read_chart_text(
                    reader,
                    processed,
                    allowlist=(
                        region_allowlists.get(region_name)
                        if region_allowlists is not None
                        else None
                    ),
                )

                for points, text, confidence in results:
                    raw_text, debug = _normalize_cell_region_text(
                        region_name,
                        (text or "").strip(),
                        subcrop,
                    )
                    if not raw_text:
                        continue

                    confidence_value = float(confidence)
                    xs = [x0 + rx0 + point[0] * inverse_scale for point in points]
                    ys = [y0 + ry0 + point[1] * inverse_scale for point in points]
                    bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
                    record = {
                        "text": raw_text,
                        "bbox": list(bbox),
                        "confidence": confidence_value,
                        "row_index": getattr(row, "index", None),
                        "col_index": col_index,
                        "measure_index": measure_index,
                        "region": region_name,
                        "source": source,
                    }
                    if debug is not None:
                        record["debug"] = debug

                    if confidence_value < min_confidence:
                        rejects.append(
                            {
                                **record,
                                "reason": (
                                    f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                                ),
                            }
                        )
                        continue

                    tokens.append(
                        OCRToken(
                            text=raw_text,
                            bbox=bbox,
                            confidence=confidence_value,
                            source=source,
                            row_index=getattr(row, "index", None),
                            col_index=col_index,
                            measure_index=measure_index,
                            region=region_name,
                            debug=debug,
                        )
                    )
                completed_regions += 1
                _report_cell_ocr_progress(
                    progress_callback,
                    completed=completed_regions,
                    total=total_regions,
                )
            measure_index += 1

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects


def extract_chart_root_anchor_local_ocr_tokens(
    image: np.ndarray,
    rows: list[Any],
    *,
    anchor_candidates: list[RootAnchorCandidate],
    min_confidence: float = 0.05,
    gpu: bool = False,
    ocr_scale: float = 2.0,
    measure_indices: set[int] | None = None,
    region_allowlists: dict[str, str] | None = None,
    source: str = "cell_ocr_root_anchor",
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[list[OCRToken], list[dict[str, Any]]]:
    reader = _get_reader(gpu=gpu)
    tokens: list[OCRToken] = []
    rejects: list[dict[str, Any]] = []
    scan_regions = chart_root_anchor_local_region_boxes(
        image,
        rows,
        anchor_candidates=anchor_candidates,
        measure_indices=measure_indices,
        source=source,
    )

    total_regions = len(scan_regions)
    completed_regions = 0
    for scan_region in scan_regions:
        region_name = str(scan_region["region"])
        x0, y0, x1, y1 = [
            int(round(float(value))) for value in scan_region["bbox"]
        ]
        x0 = max(0, min(image.shape[1], x0))
        x1 = max(0, min(image.shape[1], x1))
        y0 = max(0, min(image.shape[0], y0))
        y1 = max(0, min(image.shape[0], y1))
        if x1 <= x0 or y1 <= y0:
            completed_regions += 1
            _report_cell_ocr_progress(
                progress_callback,
                completed=completed_regions,
                total=total_regions,
            )
            continue

        subcrop = image[y0:y1, x0:x1].copy()
        processed = preprocess_for_ocr(subcrop, scale=ocr_scale)
        inverse_scale = 1.0 / ocr_scale
        results = _read_chart_text(
            reader,
            processed,
            allowlist=(
                region_allowlists.get(region_name)
                if region_allowlists is not None
                else None
            ),
        )

        for points, text, confidence in results:
            raw_text, normalization_debug = _normalize_cell_region_text(
                region_name,
                (text or "").strip(),
                subcrop,
            )
            if not raw_text:
                continue

            confidence_value = float(confidence)
            xs = [x0 + point[0] * inverse_scale for point in points]
            ys = [y0 + point[1] * inverse_scale for point in points]
            bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
            debug = _root_anchor_region_debug(
                normalization_debug,
                scan_region.get("anchor"),
            )
            record = {
                "text": raw_text,
                "bbox": list(bbox),
                "confidence": confidence_value,
                "row_index": scan_region.get("row_index"),
                "col_index": scan_region.get("col_index"),
                "measure_index": scan_region.get("measure_index"),
                "region": region_name,
                "source": source,
                "debug": debug,
            }

            if confidence_value < min_confidence:
                rejects.append(
                    {
                        **record,
                        "reason": (
                            f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                        ),
                    }
                )
                continue

            tokens.append(
                OCRToken(
                    text=raw_text,
                    bbox=bbox,
                    confidence=confidence_value,
                    source=source,
                    row_index=scan_region.get("row_index"),
                    col_index=scan_region.get("col_index"),
                    measure_index=scan_region.get("measure_index"),
                    region=region_name,
                    debug=debug,
                )
            )

        completed_regions += 1
        _report_cell_ocr_progress(
            progress_callback,
            completed=completed_regions,
            total=total_regions,
        )

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects


def extract_chart_row_ocr_tokens(
    image: np.ndarray,
    rows: list[Any],
    *,
    min_confidence: float = 0.05,
    gpu: bool = False,
    ocr_scale: float = 2.0,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[list[OCRToken], list[dict[str, Any]]]:
    reader = _get_reader(gpu=gpu)
    tokens: list[OCRToken] = []
    rejects: list[dict[str, Any]] = []

    regions = _row_ocr_regions(image, rows)
    total_regions = len(regions)
    completed_regions = 0
    for row_index, x0, y0, x1, y1 in regions:
        crop = image[y0:y1, x0:x1].copy()
        processed = preprocess_for_ocr(crop, scale=ocr_scale)
        inverse_scale = 1.0 / ocr_scale
        results = _read_chart_text(reader, processed)

        for points, text, confidence in results:
            raw_text = (text or "").strip()
            if not raw_text:
                continue

            confidence_value = float(confidence)
            xs = [x0 + point[0] * inverse_scale for point in points]
            ys = [y0 + point[1] * inverse_scale for point in points]
            bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
            record = {
                "text": raw_text,
                "bbox": list(bbox),
                "confidence": confidence_value,
                "row_index": row_index,
                "source": "cell_ocr_row_system",
            }

            if confidence_value < min_confidence:
                rejects.append(
                    {
                        **record,
                        "reason": (
                            f"confidence {confidence_value:.2f} < threshold {min_confidence:.2f}"
                        ),
                    }
                )
                continue

            tokens.append(
                OCRToken(
                    text=raw_text,
                    bbox=bbox,
                    confidence=confidence_value,
                    source="cell_ocr_row_system",
                    row_index=row_index,
                    region="row_system",
                )
            )

        completed_regions += 1
        _report_cell_ocr_progress(
            progress_callback,
            completed=completed_regions,
            total=total_regions,
        )

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects


def _read_chart_text(
    reader: Any,
    image: np.ndarray,
    *,
    allowlist: str | None = None,
) -> list[Any]:
    kwargs: dict[str, Any] = {"detail": 1, "paragraph": False}
    if allowlist is not None:
        kwargs["allowlist"] = allowlist
    return reader.readtext(image, **kwargs)


def _normalize_cell_region_text(
    region_name: str,
    text: str,
    image: np.ndarray,
) -> tuple[str, dict[str, Any] | None]:
    if region_name != "suffix_lower_right":
        return text, None

    normalized = normalize_suffix_ocr_text(text, image)
    debug = {
        "visual_normalization": {
            "normalizer": "visual_suffix",
            "raw_text": text,
            "normalized_text": normalized,
            "changed": normalized != text,
        }
    }
    return normalized, debug


def _count_cell_ocr_regions(
    rows: list[Any],
    *,
    measure_indices: set[int] | None = None,
    region_names: tuple[str, ...] | None = None,
) -> int:
    region_count = len(_selected_cell_ocr_regions(region_names))
    measure_index = 1
    count = 0
    for row in rows:
        boundaries = getattr(row, "boundaries", [])
        for _left, _right in zip(boundaries, boundaries[1:]):
            if measure_indices is None or measure_index in measure_indices:
                count += region_count
            measure_index += 1
    return count


def chart_cell_ocr_region_boxes(
    image: np.ndarray,
    rows: list[Any],
    *,
    measure_indices: set[int] | None = None,
    region_names: tuple[str, ...] | None = None,
    source: str = "cell_ocr",
) -> list[dict[str, Any]]:
    row_list = list(rows)
    selected_regions = _selected_cell_ocr_regions(region_names)
    boxes: list[dict[str, Any]] = []
    measure_index = 1
    for row_position, row in enumerate(row_list):
        boundaries = getattr(row, "boundaries", [])
        for col_index, (left, right) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            if measure_indices is not None and measure_index not in measure_indices:
                measure_index += 1
                continue

            cell_box = _measure_cell_box(image, row_list, row_position, row, left, right)
            if cell_box is None:
                measure_index += 1
                continue

            x0, y0, x1, y1 = cell_box
            crop_width = x1 - x0
            crop_height = y1 - y0
            for region_name, xa, xb, ya, yb in selected_regions:
                rx0 = int(crop_width * xa)
                rx1 = int(crop_width * xb)
                ry0 = int(crop_height * ya)
                ry1 = int(crop_height * yb)
                if rx1 <= rx0 or ry1 <= ry0:
                    continue

                boxes.append(
                    {
                        "source": source,
                        "region": region_name,
                        "row_index": getattr(row, "index", None),
                        "col_index": col_index,
                        "measure_index": measure_index,
                        "bbox": [
                            float(x0 + rx0),
                            float(y0 + ry0),
                            float(x0 + rx1),
                            float(y0 + ry1),
                        ],
                    }
                )
            measure_index += 1

    return boxes


def build_root_anchor_candidates(
    anchor_tokens: list[OCRToken],
    *,
    image: np.ndarray | None = None,
    rows: list[Any] | None = None,
    measure_indices: set[int] | None = None,
    anchor_hints: list[dict[str, Any]] | None = None,
) -> list[RootAnchorCandidate]:
    measure_boxes = (
        _measure_cell_boxes_by_index(image, rows)
        if image is not None and rows is not None
        else {}
    )
    raw_by_measure: dict[int, list[RootAnchorCandidate]] = defaultdict(list)
    for token in anchor_tokens:
        if token.measure_index is None:
            continue
        if measure_indices is not None and token.measure_index not in measure_indices:
            continue

        raw_by_measure[token.measure_index].extend(
            _split_root_anchor_token(token)
        )

    hints_by_measure: dict[int, list[RootAnchorCandidate]] = defaultdict(list)
    for hint in anchor_hints or []:
        candidate = _root_anchor_candidate_from_hint(hint)
        if candidate is None:
            continue
        if measure_indices is not None and candidate.measure_index not in measure_indices:
            continue
        hints_by_measure[candidate.measure_index].append(candidate)

    anchors: list[RootAnchorCandidate] = []
    measure_indexes = sorted(set(raw_by_measure) | set(hints_by_measure))
    for measure_index in measure_indexes:
        measure_box = measure_boxes.get(measure_index)
        measure_width = (
            max(1.0, float(measure_box[2] - measure_box[0]))
            if measure_box is not None
            else _anchor_measure_width(
                [*raw_by_measure[measure_index], *hints_by_measure[measure_index]]
            )
        )
        measure_candidates = _root_anchor_candidates_for_measure(
            scan_candidates=raw_by_measure[measure_index],
            hint_candidates=hints_by_measure[measure_index],
            measure_width=measure_width,
        )
        threshold = max(22.0, measure_width * 0.075)
        groups: list[list[RootAnchorCandidate]] = []
        for candidate in sorted(
            measure_candidates,
            key=lambda item: item.center_x,
        ):
            if (
                not groups
                or abs(candidate.center_x - _anchor_group_center(groups[-1]))
                > threshold
            ):
                groups.append([candidate])
            else:
                groups[-1].append(candidate)

        for anchor_index, group in enumerate(groups, start=1):
            candidate = max(
                group,
                key=lambda item: _root_anchor_score(
                    item,
                    measure_width=measure_width,
                ),
            )
            anchors.append(
                RootAnchorCandidate(
                    measure_index=candidate.measure_index,
                    anchor_index=anchor_index,
                    root=candidate.root,
                    center_x=candidate.center_x,
                    bbox=candidate.bbox,
                    confidence=candidate.confidence,
                    source_text=candidate.source_text,
                    source_bbox=candidate.source_bbox,
                    row_index=candidate.row_index,
                    col_index=candidate.col_index,
                )
            )

    return anchors


def chart_root_anchor_local_region_boxes(
    image: np.ndarray,
    rows: list[Any],
    *,
    anchor_candidates: list[RootAnchorCandidate],
    measure_indices: set[int] | None = None,
    source: str = "cell_ocr_root_anchor",
) -> list[dict[str, Any]]:
    measure_boxes = _measure_cell_boxes_by_index(image, rows)
    anchors_by_measure: dict[int, list[RootAnchorCandidate]] = defaultdict(list)
    for anchor in anchor_candidates:
        if measure_indices is not None and anchor.measure_index not in measure_indices:
            continue
        anchors_by_measure[anchor.measure_index].append(anchor)

    boxes: list[dict[str, Any]] = []
    for measure_index in sorted(anchors_by_measure):
        measure_box = measure_boxes.get(measure_index)
        if measure_box is None:
            continue

        anchors = sorted(
            anchors_by_measure[measure_index],
            key=lambda item: item.center_x,
        )
        for index, anchor in enumerate(anchors):
            next_anchor_x = (
                anchors[index + 1].center_x if index + 1 < len(anchors) else None
            )
            for region_name, bbox in _root_anchor_local_region_boxes(
                anchor,
                measure_box=measure_box,
                next_anchor_x=next_anchor_x,
            ):
                boxes.append(
                    {
                        "source": source,
                        "region": region_name,
                        "row_index": anchor.row_index,
                        "col_index": anchor.col_index,
                        "measure_index": measure_index,
                        "anchor_index": anchor.anchor_index,
                        "bbox": [float(value) for value in bbox],
                        "anchor": anchor.to_dict(),
                    }
                )

    return boxes


def chart_row_ocr_region_boxes(
    image: np.ndarray,
    rows: list[Any],
) -> list[dict[str, Any]]:
    return [
        {
            "source": "cell_ocr_row_system",
            "region": "row_system",
            "row_index": row_index,
            "bbox": [float(x0), float(y0), float(x1), float(y1)],
        }
        for row_index, x0, y0, x1, y1 in _row_ocr_regions(image, rows)
    ]


def _report_cell_ocr_progress(
    progress_callback: Callable[[int, int], None] | None,
    *,
    completed: int,
    total: int,
) -> None:
    if progress_callback is not None:
        progress_callback(completed, total)


def _measure_cell_box(
    image: np.ndarray,
    rows: list[Any],
    row_position: int,
    row: Any,
    left: Any,
    right: Any,
) -> tuple[int, int, int, int] | None:
    x0 = int(max(0, float(left.x) + 8))
    x1 = int(min(image.shape[1], float(right.x) - 8))
    next_y_top = (
        float(getattr(rows[row_position + 1], "y_top"))
        if row_position + 1 < len(rows)
        else float(image.shape[0])
    )
    y0 = int(max(0, float(row.y_top) - 35))
    y1 = int(min(image.shape[0], next_y_top - 8, float(row.y_bottom) + 80))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _measure_cell_boxes_by_index(
    image: np.ndarray,
    rows: list[Any],
) -> dict[int, tuple[int, int, int, int]]:
    row_list = list(rows)
    boxes: dict[int, tuple[int, int, int, int]] = {}
    measure_index = 1
    for row_position, row in enumerate(row_list):
        boundaries = getattr(row, "boundaries", [])
        for _col_index, (left, right) in enumerate(
            zip(boundaries, boundaries[1:]),
            start=1,
        ):
            box = _measure_cell_box(image, row_list, row_position, row, left, right)
            if box is not None:
                boxes[measure_index] = box
            measure_index += 1
    return boxes


def _split_root_anchor_token(token: OCRToken) -> list[RootAnchorCandidate]:
    compact = re.sub(r"\s+", "", token.text or "")
    letters = [char.upper() for char in compact if char.upper() in "ABCDEFG"]
    if token.measure_index is None or not letters:
        return []

    x0, y0, x1, y1 = token.bbox
    width = max(1.0, x1 - x0)
    letter_width = width / len(letters)
    candidates: list[RootAnchorCandidate] = []
    for index, letter in enumerate(letters):
        lx0 = x0 + letter_width * index
        lx1 = x0 + letter_width * (index + 1)
        candidates.append(
            RootAnchorCandidate(
                measure_index=token.measure_index,
                anchor_index=0,
                root=letter,
                center_x=(lx0 + lx1) / 2.0,
                bbox=(float(lx0), float(y0), float(lx1), float(y1)),
                confidence=token.confidence,
                source_text=token.text,
                source_bbox=token.bbox,
                row_index=token.row_index,
                col_index=token.col_index,
            )
        )
    return candidates


def _root_anchor_candidate_from_hint(
    hint: dict[str, Any],
) -> RootAnchorCandidate | None:
    try:
        measure_index = int(hint["measure_index"])
        root = str(hint["root"]).upper()
        center_x = float(hint["center_x"])
        bbox_values = hint["bbox"]
        source_bbox_values = hint.get("source_bbox") or bbox_values
        bbox = tuple(float(value) for value in bbox_values)
        source_bbox = tuple(float(value) for value in source_bbox_values)
    except (KeyError, TypeError, ValueError):
        return None
    if root not in "ABCDEFG" or len(bbox) != 4 or len(source_bbox) != 4:
        return None

    confidence = hint.get("confidence")
    return RootAnchorCandidate(
        measure_index=measure_index,
        anchor_index=int(hint.get("anchor_index") or 0),
        root=root,
        center_x=center_x,
        bbox=bbox,
        confidence=float(confidence)
        if isinstance(confidence, int | float)
        else None,
        source_text=str(hint.get("source_text") or ""),
        source_bbox=source_bbox,
        row_index=int(hint["row_index"]) if hint.get("row_index") is not None else None,
        col_index=int(hint["col_index"]) if hint.get("col_index") is not None else None,
    )


def _root_anchor_candidates_for_measure(
    *,
    scan_candidates: list[RootAnchorCandidate],
    hint_candidates: list[RootAnchorCandidate],
    measure_width: float,
) -> list[RootAnchorCandidate]:
    if not hint_candidates:
        return scan_candidates

    refined = [
        _refine_root_anchor_hint(
            hint,
            scan_candidates=scan_candidates,
            measure_width=measure_width,
        )
        for hint in hint_candidates
    ]
    if len(refined) >= 2:
        return refined
    return [*refined, *scan_candidates]


def _refine_root_anchor_hint(
    hint: RootAnchorCandidate,
    *,
    scan_candidates: list[RootAnchorCandidate],
    measure_width: float,
) -> RootAnchorCandidate:
    max_distance = max(34.0, measure_width * 0.15)
    matches = [
        candidate
        for candidate in scan_candidates
        if candidate.root == hint.root
        and abs(candidate.center_x - hint.center_x) <= max_distance
    ]
    if not matches:
        return hint

    best = min(matches, key=lambda candidate: abs(candidate.center_x - hint.center_x))
    return RootAnchorCandidate(
        measure_index=best.measure_index,
        anchor_index=hint.anchor_index,
        root=best.root,
        center_x=best.center_x,
        bbox=best.bbox,
        confidence=best.confidence,
        source_text=best.source_text,
        source_bbox=best.source_bbox,
        row_index=best.row_index,
        col_index=best.col_index,
    )


def _anchor_measure_width(candidates: list[RootAnchorCandidate]) -> float:
    if not candidates:
        return 1.0
    x0 = min(candidate.bbox[0] for candidate in candidates)
    x1 = max(candidate.bbox[2] for candidate in candidates)
    return max(1.0, x1 - x0)


def _anchor_group_center(group: list[RootAnchorCandidate]) -> float:
    return float(np.mean([candidate.center_x for candidate in group]))


def _root_anchor_score(
    candidate: RootAnchorCandidate,
    *,
    measure_width: float,
) -> float:
    confidence = float(candidate.confidence or 0.0)
    candidate_width = max(1.0, candidate.bbox[2] - candidate.bbox[0])
    return confidence * 3.0 - candidate_width / max(measure_width, 1.0)


def _root_anchor_local_region_boxes(
    anchor: RootAnchorCandidate,
    *,
    measure_box: tuple[int, int, int, int],
    next_anchor_x: float | None,
) -> list[tuple[str, tuple[float, float, float, float]]]:
    mx0, my0, mx1, my1 = [float(value) for value in measure_box]
    measure_width = max(1.0, mx1 - mx0)
    measure_height = max(1.0, my1 - my0)
    cx = anchor.center_x
    right_limit = mx1
    if next_anchor_x is not None:
        right_limit = min(right_limit, next_anchor_x - measure_width * 0.035)

    regions = [
        (
            "root",
            (
                cx - measure_width * 0.13,
                my0 + measure_height * 0.05,
                min(cx + measure_width * 0.15, right_limit),
                my0 + measure_height * 0.77,
            ),
        ),
        (
            "root_accidental",
            (
                cx + measure_width * 0.01,
                my0,
                min(cx + measure_width * 0.20, right_limit),
                my0 + measure_height * 0.50,
            ),
        ),
        (
            "suffix_lower_right",
            (
                cx - measure_width * 0.02,
                my0 + measure_height * 0.34,
                min(cx + measure_width * 0.46, right_limit),
                my0 + measure_height * 0.76,
            ),
        ),
    ]

    clamped: list[tuple[str, tuple[float, float, float, float]]] = []
    for region_name, bbox in regions:
        x0, y0, x1, y1 = bbox
        x0 = max(mx0, min(mx1, x0))
        x1 = max(mx0, min(mx1, x1))
        y0 = max(my0, min(my1, y0))
        y1 = max(my0, min(my1, y1))
        if x1 - x0 < 4.0 or y1 - y0 < 4.0:
            continue
        clamped.append((region_name, (x0, y0, x1, y1)))
    return clamped


def _root_anchor_region_debug(
    normalization_debug: dict[str, Any] | None,
    anchor: object,
) -> dict[str, Any]:
    debug = dict(normalization_debug or {})
    if isinstance(anchor, dict):
        debug["root_anchor"] = anchor
    return debug


# (region_name, x_start, x_end, y_start, y_end)
def _cell_ocr_regions() -> list[tuple[str, float, float, float, float]]:
    return [
        ("full", 0.0, 1.0, 0.0, 1.0),
        ("top", 0.0, 1.0, 0.0, 0.70),
        ("bottom", 0.0, 1.0, 0.30, 1.0),
        ("left", 0.0, 0.58, 0.0, 1.0),
        ("right", 0.42, 1.0, 0.0, 1.0),
        ("low", 0.0, 1.0, 0.55, 1.0),
        ("root", 0.0, 0.28, 0.05, 0.77),
        ("root_accidental", 0.16, 0.33, 0.0, 0.50),
        ("suffix_lower_right", 0.20, 0.55, 0.34, 0.76),
        ("root_anchor_scan", 0.0, 1.0, 0.05, 0.77),
        ("root_wide", 0.0, 1.0, 0.05, 0.77),
        ("root_accidental_wide", 0.0, 1.0, 0.0, 0.42),
        ("suffix_wide", 0.0, 1.0, 0.34, 0.76),
        ("slash_bass_below_root", 0.0, 0.64, 0.54, 1.0),
    ]


def _selected_cell_ocr_regions(
    region_names: tuple[str, ...] | None,
) -> list[tuple[str, float, float, float, float]]:
    regions = _cell_ocr_regions()
    if region_names is None:
        return regions

    wanted = set(region_names)
    return [region for region in regions if region[0] in wanted]


def _row_ocr_regions(
    image: np.ndarray,
    rows: list[Any],
) -> list[tuple[int, int, int, int, int]]:
    height, width = image.shape[:2]
    row_list = list(rows)
    regions: list[tuple[int, int, int, int, int]] = []
    for row_position, row in enumerate(row_list):
        boundaries = getattr(row, "boundaries", [])
        if len(boundaries) < 2:
            continue

        next_y_top = (
            float(getattr(row_list[row_position + 1], "y_top"))
            if row_position + 1 < len(row_list)
            else float(height)
        )
        x0 = int(max(0, float(boundaries[0].x) + 8))
        x1 = int(min(width, float(boundaries[-1].x) - 8))
        y0 = int(max(0, float(row.y_top) - 35))
        y1 = int(min(height, next_y_top - 8, float(row.y_bottom) + 80))
        if x1 <= x0 or y1 <= y0:
            continue

        regions.append((int(getattr(row, "index")), x0, y0, x1, y1))

    return regions
