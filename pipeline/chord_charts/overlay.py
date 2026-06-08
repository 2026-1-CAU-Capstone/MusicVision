from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import textwrap
from typing import Any

import cv2
import numpy as np


CHORD_CHART_OVERLAY_FILENAME = "chord_chart_overlay.png"
CHORD_CHART_OCR_DEBUG_OVERLAY_FILENAME = "chord_chart_ocr_debug_overlay.png"
CHORD_CHART_SCAN_BOUNDARY_OVERLAY_FILENAME = "chord_chart_scan_boundary_overlay.png"
CHORD_CHART_ROOT_OCR_BBOX_OVERLAY_FILENAME = "chord_chart_root_ocr_bbox_overlay.png"
MEASURE_COLOUR = (40, 120, 220)
CHORD_COLOUR = (30, 170, 60)
SYMBOL_COLOUR = (220, 140, 30)
NAVIGATION_COLOUR = (190, 60, 190)
SCAN_PAGE_COLOUR = (120, 120, 120)
SCAN_ROW_COLOUR = (0, 150, 180)
SCAN_ROOT_COLOUR = (30, 110, 235)
SCAN_ACCIDENTAL_COLOUR = (155, 80, 210)
SCAN_SUFFIX_COLOUR = (235, 130, 20)
SCAN_SLASH_BASS_COLOUR = (30, 170, 155)
OCR_ACCEPTED_COLOUR = (15, 145, 65)
OCR_REJECTED_COLOUR = (210, 45, 45)
PANEL_BG_COLOUR = (255, 255, 255)
PANEL_TEXT_COLOUR = (25, 25, 25)
PANEL_MUTED_COLOUR = (95, 95, 95)


@dataclass(frozen=True)
class _PanelLine:
    text: str
    colour: tuple[int, int, int] = PANEL_TEXT_COLOUR
    scale: float = 0.48
    thickness: int = 1


def write_chord_chart_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    overlay = render_chord_chart_overlay(image=image, pages=pages)
    output_path = output_dir / CHORD_CHART_OVERLAY_FILENAME
    cv2.imwrite(str(output_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    return output_path


def write_chord_chart_ocr_debug_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    chart_ocr: dict[str, Any],
    ocr_tokens: list[Any],
    ocr_rejects: list[dict[str, Any]],
    scan_regions: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    overlay = render_chord_chart_ocr_debug_overlay(
        image=image,
        pages=pages,
        chart_ocr=chart_ocr,
        ocr_tokens=ocr_tokens,
        ocr_rejects=ocr_rejects,
        scan_regions=scan_regions,
    )
    output_path = output_dir / CHORD_CHART_OCR_DEBUG_OVERLAY_FILENAME
    cv2.imwrite(str(output_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    return output_path


def write_chord_chart_scan_boundary_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    scan_regions: list[dict[str, Any]],
    chart_ocr: dict[str, Any] | None = None,
    output_dir: Path,
) -> Path:
    overlay = render_chord_chart_scan_boundary_overlay(
        image=image,
        pages=pages,
        scan_regions=scan_regions,
        chart_ocr=chart_ocr,
    )
    output_path = output_dir / CHORD_CHART_SCAN_BOUNDARY_OVERLAY_FILENAME
    cv2.imwrite(str(output_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    return output_path


def write_chord_chart_root_ocr_bbox_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    chart_ocr: dict[str, Any],
    output_dir: Path,
) -> Path:
    overlay = render_chord_chart_root_ocr_bbox_overlay(
        image=image,
        pages=pages,
        chart_ocr=chart_ocr,
    )
    output_path = output_dir / CHORD_CHART_ROOT_OCR_BBOX_OVERLAY_FILENAME
    cv2.imwrite(str(output_path), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    return output_path


def render_chord_chart_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
) -> np.ndarray:
    overlay = image.copy()

    for page in pages:
        for system in page.get("systems") or []:
            for measure in system.get("measures") or []:
                _draw_box(overlay, measure.get("bbox"), MEASURE_COLOUR, thickness=2)
                label = str(measure.get("index", "?"))
                _draw_text(overlay, label, measure.get("bbox"), MEASURE_COLOUR)

                for chord in measure.get("chords") or []:
                    _draw_box(overlay, chord.get("bbox"), CHORD_COLOUR, thickness=3)
                    _draw_text(
                        overlay,
                        str(chord.get("text_norm", "")),
                        chord.get("bbox"),
                        CHORD_COLOUR,
                    )

                for symbol in measure.get("symbols") or []:
                    _draw_box(overlay, symbol.get("bbox"), SYMBOL_COLOUR, thickness=3)

                for navigation in measure.get("navigation") or []:
                    _draw_box(
                        overlay,
                        navigation.get("bbox"),
                        NAVIGATION_COLOUR,
                        thickness=3,
                    )

    return overlay


def render_chord_chart_ocr_debug_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    chart_ocr: dict[str, Any],
    ocr_tokens: list[Any],
    ocr_rejects: list[dict[str, Any]],
    scan_regions: list[dict[str, Any]],
) -> np.ndarray:
    marked_image = image.copy()
    _draw_final_measure_boxes(marked_image, pages, draw_labels=False, draw_chords=False)
    _draw_debug_value_labels(
        marked_image,
        chart_ocr=chart_ocr,
    )
    _draw_debug_legend(marked_image)
    return marked_image


def render_chord_chart_scan_boundary_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    scan_regions: list[dict[str, Any]],
    chart_ocr: dict[str, Any] | None = None,
) -> np.ndarray:
    marked_image = image.copy()
    _draw_final_measure_boxes(marked_image, pages, draw_labels=False, draw_chords=False)
    _draw_scan_boundary_regions(
        marked_image,
        scan_regions=scan_regions,
        chart_ocr=chart_ocr,
    )
    _draw_scan_boundary_legend(marked_image)
    return marked_image


def render_chord_chart_root_ocr_bbox_overlay(
    *,
    image: np.ndarray,
    pages: list[dict[str, Any]],
    chart_ocr: dict[str, Any],
) -> np.ndarray:
    marked_image = image.copy()
    _draw_final_measure_boxes(marked_image, pages, draw_labels=False, draw_chords=False)
    _draw_root_ocr_bbox_fragments(marked_image, chart_ocr=chart_ocr)
    _draw_root_ocr_bbox_legend(marked_image)
    return marked_image


def _draw_final_measure_boxes(
    image: np.ndarray,
    pages: list[dict[str, Any]],
    *,
    draw_labels: bool = False,
    draw_chords: bool = True,
) -> None:
    for page in pages:
        for system in page.get("systems") or []:
            for measure in system.get("measures") or []:
                _draw_box(image, measure.get("bbox"), MEASURE_COLOUR, thickness=1)
                if draw_labels:
                    _draw_label_box(
                        image,
                        _final_measure_display_label(measure),
                        measure.get("bbox"),
                        CHORD_COLOUR,
                        position="inside",
                    )
                if draw_chords:
                    for chord in measure.get("chords") or []:
                        _draw_box(image, chord.get("bbox"), CHORD_COLOUR, thickness=3)


def _draw_debug_value_labels(
    image: np.ndarray,
    *,
    chart_ocr: dict[str, Any],
) -> None:
    for entry in _accepted_semantic_assembly_entries(chart_ocr):
        fragments = _selected_semantic_fragments(entry)
        chord_bbox = _union_debug_fragment_bbox(fragments)
        if chord_bbox is not None:
            _draw_box(image, chord_bbox, CHORD_COLOUR, thickness=3)
            _draw_label_box(
                image,
                _truncate_label(str(entry.get("text") or ""), limit=18),
                chord_bbox,
                CHORD_COLOUR,
                position="left_top",
            )

        for fragment in _semantic_fragments_by_role(fragments, "suffix"):
            _draw_box(image, fragment.get("bbox"), SCAN_SUFFIX_COLOUR, thickness=2)
            _draw_label_box(
                image,
                _truncate_label(str(fragment.get("text") or ""), limit=12),
                fragment.get("bbox"),
                SCAN_SUFFIX_COLOUR,
                position="below",
            )

        for fragment in _semantic_fragments_by_role(fragments, "accidental"):
            _draw_box(image, fragment.get("bbox"), SCAN_ACCIDENTAL_COLOUR, thickness=2)
            _draw_label_box(
                image,
                _truncate_label(str(fragment.get("text") or ""), limit=12),
                fragment.get("bbox"),
                SCAN_ACCIDENTAL_COLOUR,
                position="right",
            )


def _draw_scan_boundary_regions(
    image: np.ndarray,
    *,
    scan_regions: list[dict[str, Any]],
    chart_ocr: dict[str, Any] | None,
) -> None:
    for region in _selected_scan_boundary_regions(
        scan_regions,
        chart_ocr=chart_ocr,
    ):
        if not _visible_scan_boundary_region(region):
            continue
        colour = _scan_region_colour(region)
        bbox = region.get("bbox")
        _draw_box(image, bbox, colour, thickness=2)
        _draw_label_box(
            image,
            _scan_boundary_label(region),
            bbox,
            colour,
            position=_scan_boundary_label_position(region),
        )


def _draw_root_ocr_bbox_fragments(
    image: np.ndarray,
    *,
    chart_ocr: dict[str, Any],
) -> None:
    for fragment in _root_ocr_bbox_fragments(chart_ocr):
        colour = (
            SCAN_ROOT_COLOUR
            if fragment.get("status") == "accepted"
            else OCR_REJECTED_COLOUR
        )
        bbox = fragment.get("bbox")
        _draw_box(image, bbox, colour, thickness=2)
        _draw_label_box(
            image,
            _root_ocr_bbox_label(fragment),
            bbox,
            colour,
            position="above",
        )


def _root_ocr_bbox_fragments(chart_ocr: dict[str, Any]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    strategy = chart_ocr.get("strategy")
    if not isinstance(strategy, dict):
        return fragments
    entries = strategy.get("semantic_assembly")
    if not isinstance(entries, list):
        return fragments

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "unknown")
        measure_index = _maybe_int(entry.get("measure_index"))
        for fragment in entry.get("fragments") or []:
            if not isinstance(fragment, dict) or fragment.get("role") != "root":
                continue
            key = (
                status,
                measure_index,
                str(fragment.get("text") or ""),
                _bbox_key(fragment.get("bbox")),
            )
            if key in seen:
                continue
            seen.add(key)
            fragments.append(
                {
                    **fragment,
                    "status": status,
                    "measure_index": measure_index,
                    "chord_text": entry.get("text"),
                }
            )
    return fragments


def _root_ocr_bbox_label(fragment: dict[str, Any]) -> str:
    parts = []
    measure_index = _maybe_int(fragment.get("measure_index"))
    if measure_index is not None:
        parts.append(f"m{measure_index:02d}")
    parts.append(str(fragment.get("text") or "?"))
    if fragment.get("status") != "accepted":
        parts.append("rejected")
    return _truncate_label(" ".join(parts), limit=18)


def _selected_scan_boundary_regions(
    scan_regions: list[dict[str, Any]],
    *,
    chart_ocr: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    visible_regions = [
        region
        for region in scan_regions
        if isinstance(region, dict) and _visible_scan_boundary_region(region)
    ]
    if chart_ocr is not None:
        final_measures = _accepted_semantic_measure_indices(chart_ocr)
        final_anchor_indices = _accepted_semantic_anchor_indices(chart_ocr)
        if final_measures:
            selected = []
            for region in visible_regions:
                measure_index = _maybe_int(region.get("measure_index"))
                if measure_index in final_anchor_indices:
                    if (
                        region.get("source") == "cell_ocr_root_anchor"
                        and _maybe_int(region.get("anchor_index"))
                        in final_anchor_indices[measure_index]
                    ):
                        selected.append(region)
                    continue
                if measure_index in final_measures:
                    if region.get("source") != "cell_ocr_root_anchor":
                        selected.append(region)
                    continue
                selected.append(region)
            return _dedupe_scan_boundary_regions(selected)

    anchor_measure_indices = {
        int(region["measure_index"])
        for region in visible_regions
        if region.get("source") == "cell_ocr_root_anchor"
        and region.get("measure_index") is not None
    }
    selected: list[dict[str, Any]] = []
    for region in visible_regions:
        measure_index = _maybe_int(region.get("measure_index"))
        if measure_index in anchor_measure_indices:
            if region.get("source") == "cell_ocr_root_anchor":
                selected.append(region)
            continue
        selected.append(region)
    return _dedupe_scan_boundary_regions(selected)


def _accepted_semantic_measure_indices(chart_ocr: dict[str, Any]) -> set[int]:
    measure_indices: set[int] = set()
    for entry in _accepted_semantic_assembly_entries(chart_ocr):
        measure_index = _maybe_int(entry.get("measure_index"))
        if measure_index is not None:
            measure_indices.add(measure_index)
    return measure_indices


def _accepted_semantic_anchor_indices(
    chart_ocr: dict[str, Any],
) -> dict[int, set[int]]:
    anchor_indices: dict[int, set[int]] = {}
    for entry in _accepted_semantic_assembly_entries(chart_ocr):
        entry_measure_index = _maybe_int(entry.get("measure_index"))
        for fragment in entry.get("fragments") or []:
            if not isinstance(fragment, dict):
                continue
            root_anchor = (fragment.get("debug") or {}).get("root_anchor")
            if not isinstance(root_anchor, dict):
                continue
            measure_index = _maybe_int(
                root_anchor.get("measure_index") or fragment.get("measure_index")
            )
            if measure_index is None:
                measure_index = entry_measure_index
            anchor_index = _maybe_int(root_anchor.get("anchor_index"))
            if measure_index is None or anchor_index is None:
                continue
            anchor_indices.setdefault(measure_index, set()).add(anchor_index)
    return anchor_indices


def _dedupe_scan_boundary_regions(
    scan_regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for region in scan_regions:
        key = (
            region.get("source"),
            region.get("region"),
            _maybe_int(region.get("measure_index")),
            _maybe_int(region.get("anchor_index")),
            _bbox_key(region.get("bbox")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(region)
    return deduped


def _visible_scan_boundary_region(region: dict[str, Any]) -> bool:
    return str(region.get("region") or "") in {
        "root",
        "root_accidental",
        "suffix_lower_right",
    }


def _scan_boundary_label(region: dict[str, Any]) -> str:
    source = _short_scan_source_label(region)
    measure = _maybe_int(region.get("measure_index"))
    anchor = _maybe_int(region.get("anchor_index"))
    region_name = str(region.get("region") or "?")
    label_parts = []
    if measure is not None:
        label_parts.append(f"m{measure:02d}")
    if anchor is not None:
        label_parts.append(f"a{anchor}")
    label_parts.append(_short_region_name(region_name))
    if source:
        label_parts.append(source)
    return " ".join(label_parts)


def _short_scan_source_label(region: dict[str, Any]) -> str:
    source = str(region.get("source") or "")
    if source == "cell_ocr_root_anchor":
        return "anchor"
    if source == "cell_ocr_root_anchor_probe":
        return "probe"
    if source in {"cell_ocr_semantic", "cell_ocr_targeted"}:
        return "cell"
    if source == "cell_ocr_row_system":
        return "row"
    if source == "page_ocr":
        return "page"
    if source.startswith("cell_ocr"):
        return "cell"
    return source or "scan"


def _short_region_name(region_name: str) -> str:
    return {
        "root": "root",
        "root_accidental": "acc",
        "suffix_lower_right": "suffix",
    }.get(region_name, region_name)


def _scan_boundary_label_position(region: dict[str, Any]) -> str:
    region_name = str(region.get("region") or "")
    if region_name == "root":
        return "above"
    if region_name == "root_accidental":
        return "right"
    if region_name == "suffix_lower_right":
        return "below"
    return "inside"


def _accepted_semantic_assembly_entries(chart_ocr: dict[str, Any]) -> list[dict[str, Any]]:
    strategy = chart_ocr.get("strategy")
    if not isinstance(strategy, dict):
        return []
    entries = strategy.get("semantic_assembly")
    if not isinstance(entries, list):
        return []
    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("status") == "accepted"
    ]


def _selected_semantic_fragments(entry: dict[str, Any]) -> list[dict[str, Any]]:
    fragments = [
        fragment
        for fragment in entry.get("fragments") or []
        if isinstance(fragment, dict)
    ]
    roots = _semantic_fragments_by_role(fragments, "root")
    accidentals = _dedupe_semantic_fragments(
        _semantic_fragments_by_role(fragments, "accidental")
    )
    suffixes = _dedupe_semantic_fragments(
        [
            fragment
            for fragment in _semantic_fragments_by_role(fragments, "suffix")
            if _visible_semantic_suffix_fragment(fragment)
        ]
    )
    return [*roots, *accidentals, *suffixes]


def _semantic_fragments_by_role(
    fragments: list[dict[str, Any]],
    role: str,
) -> list[dict[str, Any]]:
    return [fragment for fragment in fragments if fragment.get("role") == role]


def _visible_semantic_suffix_fragment(fragment: dict[str, Any]) -> bool:
    compact = re.sub(r"\s+", "", str(fragment.get("text") or ""))
    if not compact:
        return False
    return re.fullmatch(r"[A-Ga-g]+", compact) is None


def _dedupe_semantic_fragments(
    fragments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for fragment in fragments:
        duplicate_index = _duplicate_semantic_fragment_index(fragment, deduped)
        if duplicate_index is None:
            deduped.append(fragment)
            continue
        if _semantic_fragment_score(fragment) > _semantic_fragment_score(
            deduped[duplicate_index]
        ):
            deduped[duplicate_index] = fragment
    return deduped


def _duplicate_semantic_fragment_index(
    fragment: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> int | None:
    for index, candidate in enumerate(candidates):
        if fragment.get("role") != candidate.get("role"):
            continue
        if str(fragment.get("text") or "") != str(candidate.get("text") or ""):
            continue
        if _bbox_overlap_ratio(fragment.get("bbox"), candidate.get("bbox")) >= 0.45:
            return index
    return None


def _semantic_fragment_score(fragment: dict[str, Any]) -> tuple[float, float]:
    confidence = fragment.get("confidence")
    confidence_score = float(confidence) if isinstance(confidence, int | float) else 0.0
    return confidence_score, -_bbox_area(fragment.get("bbox"))


def _bbox_overlap_ratio(first: object, second: object) -> float:
    if not _valid_bbox(first) or not _valid_bbox(second):
        return 0.0
    ax0, ay0, ax1, ay1 = [float(value) for value in first]  # type: ignore[arg-type]
    bx0, by0, bx1, by1 = [float(value) for value in second]  # type: ignore[arg-type]
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    smaller_area = min(_bbox_area(first), _bbox_area(second))
    if smaller_area <= 0.0:
        return 0.0
    return intersection / smaller_area


def _bbox_area(bbox: object) -> float:
    if not _valid_bbox(bbox):
        return 0.0
    x0, y0, x1, y1 = [float(value) for value in bbox]  # type: ignore[arg-type]
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _union_debug_fragment_bbox(
    fragments: list[dict[str, Any]],
) -> tuple[float, float, float, float] | None:
    boxes = [fragment.get("bbox") for fragment in fragments]
    valid_boxes = [box for box in boxes if _valid_bbox(box)]
    if not valid_boxes:
        return None
    return (
        min(float(box[0]) for box in valid_boxes),  # type: ignore[index]
        min(float(box[1]) for box in valid_boxes),  # type: ignore[index]
        max(float(box[2]) for box in valid_boxes),  # type: ignore[index]
        max(float(box[3]) for box in valid_boxes),  # type: ignore[index]
    )


def _draw_debug_legend(image: np.ndarray) -> None:
    lines = [
        "green: final chord (semantic chord)",
        "orange: suffix",
        "purple: accidental",
    ]
    x = 12
    y = 22
    for index, line in enumerate(lines):
        _draw_label_at(
            image,
            line,
            x=x,
            y=y + index * 24,
            colour=PANEL_TEXT_COLOUR,
            fill=(255, 255, 255),
        )


def _draw_scan_boundary_legend(image: np.ndarray) -> None:
    lines = [
        "blue: root scan boundary",
        "purple: accidental scan boundary",
        "orange: suffix scan boundary",
        "accepted semantic anchors show anchor-local scan boxes only",
    ]
    x = 12
    y = 22
    for index, line in enumerate(lines):
        _draw_label_at(
            image,
            line,
            x=x,
            y=y + index * 24,
            colour=PANEL_TEXT_COLOUR,
            fill=(255, 255, 255),
        )


def _draw_root_ocr_bbox_legend(image: np.ndarray) -> None:
    lines = [
        "blue: accepted root OCR result bbox",
        "red: rejected root OCR result bbox",
        "boxes are OCR result boxes, not scan windows",
    ]
    x = 12
    y = 22
    for index, line in enumerate(lines):
        _draw_label_at(
            image,
            line,
            x=x,
            y=y + index * 24,
            colour=PANEL_TEXT_COLOUR,
            fill=(255, 255, 255),
        )


def _debug_panel_lines(
    *,
    pages: list[dict[str, Any]],
    chart_ocr: dict[str, Any],
    ocr_tokens: list[Any],
    ocr_rejects: list[dict[str, Any]],
    scan_regions: list[dict[str, Any]],
) -> list[_PanelLine]:
    lines = [
        _PanelLine("Chord Chart OCR Debug Overlay", thickness=2, scale=0.62),
        _PanelLine("Image labels are boxes only; text is listed here to avoid overlap."),
        _PanelLine(
            (
                "Legend: grey=page/measure, teal=row scan, blue=root/anchor, "
                "purple=accidental, orange=suffix, green=OCR hit, red=reject"
            ),
            colour=PANEL_MUTED_COLOUR,
        ),
        _PanelLine(""),
        _PanelLine("1. Scanned Regions", thickness=2),
    ]
    for index, region in enumerate(scan_regions, start=1):
        lines.append(
            _PanelLine(
                _scan_region_label(index, region),
                colour=_scan_region_colour(region),
            )
        )

    lines.extend(
        [
            _PanelLine(""),
            _PanelLine("2. OCR Results By Detection Box", thickness=2),
        ]
    )
    accepted_lookup = _token_lookup(chart_ocr.get("accepted_tokens") or [])
    unassigned_lookup = _token_lookup(chart_ocr.get("unassigned_tokens") or [])
    for index, token in enumerate(ocr_tokens, start=1):
        token_dict = _token_to_dict(token)
        key = _token_key(token_dict)
        accepted = accepted_lookup.get(key)
        unassigned = unassigned_lookup.get(key)
        raw = _ocr_raw_text(token_dict)
        normalized = str(token_dict.get("text") or "")
        corrected = (
            str(accepted.get("text_norm"))
            if accepted is not None and accepted.get("text_norm") is not None
            else "-"
        )
        status = "accepted"
        if accepted is not None:
            status = str(accepted.get("kind") or "accepted")
        elif unassigned is not None:
            status = f"unassigned: {unassigned.get('reason')}"
        else:
            status = "raw only"
        lines.append(
            _PanelLine(
                (
                    f"{index:03d} {status} {token_dict.get('source', '?')}"
                    f"{_measure_region_suffix(token_dict)} raw={raw!r}"
                    f" norm={normalized!r}"
                    f" corrected={corrected!r} conf={_confidence(token_dict)}"
                    f" bbox={_bbox_text(token_dict.get('bbox'))}"
                ),
                colour=OCR_ACCEPTED_COLOUR
                if accepted is not None
                else PANEL_MUTED_COLOUR,
            )
        )

    for index, reject in enumerate(ocr_rejects, start=1):
        lines.append(
            _PanelLine(
                (
                    f"R{index:03d} rejected {reject.get('source', '?')}"
                    f"{_measure_region_suffix(reject)} raw={str(reject.get('text') or '')!r}"
                    f" corrected={str(reject.get('text_norm') or '-')!r}"
                    f" conf={_confidence(reject)} reason={reject.get('reason', '-')}"
                    f" bbox={_bbox_text(reject.get('bbox'))}"
                ),
                colour=OCR_REJECTED_COLOUR,
            )
        )

    lines.extend(
        [
            _PanelLine(""),
            _PanelLine("3. Final Chords By Measure", thickness=2),
        ]
    )
    for measure in _iter_measures(pages):
        lines.append(_PanelLine(_final_measure_label(measure), colour=CHORD_COLOUR))

    return lines


def _ocr_token_display_label(
    token: dict[str, Any],
    *,
    accepted: dict[str, Any] | None,
    unassigned: dict[str, Any] | None,
) -> str:
    raw = str(token.get("text") or "")
    normalized_from = _ocr_raw_text(token)
    if normalized_from != raw:
        raw = f"{normalized_from}=>{raw}"
    prefix = _short_source_label(token)
    if accepted is not None:
        corrected = str(accepted.get("text_norm") or raw)
        if corrected and corrected != raw:
            return _truncate_label(f"{prefix} {raw}=>{corrected}")
        return _truncate_label(f"{prefix} {raw}")
    if unassigned is not None:
        return _truncate_label(f"{prefix} {raw}?")
    return _truncate_label(f"{prefix} {raw}")


def _rejected_token_display_label(reject: dict[str, Any]) -> str:
    raw = str(reject.get("text") or "")
    corrected = str(reject.get("text_norm") or "")
    if corrected and corrected != raw:
        return _truncate_label(f"reject {raw}=>{corrected}")
    return _truncate_label(f"reject {raw}")


def _short_source_label(payload: dict[str, Any]) -> str:
    region = payload.get("region")
    if region:
        name = str(region)
        return {
            "root_accidental": "acc",
            "suffix_lower_right": "suffix",
            "row_system": "row",
        }.get(name, name)

    source = str(payload.get("source") or "")
    if source == "page_ocr":
        return "page"
    if source == "cell_ocr_row_system":
        return "row"
    if source.startswith("cell_ocr"):
        return "cell"
    return "ocr"


def _final_measure_display_label(measure: dict[str, Any]) -> str:
    index = int(measure.get("index") or 0)
    labels = [
        str(chord.get("text_norm") or chord.get("text_raw") or "")
        for chord in measure.get("chords") or []
    ]
    if not labels:
        labels = [
            str(chord.get("text_norm") or chord.get("text_raw") or "")
            for chord in measure.get("resolved_chords") or []
        ]
    labels = [label for label in labels if label]
    if not labels:
        return f"m{index:02d}"
    return _truncate_label(f"m{index:02d} {', '.join(labels)}")


def _truncate_label(text: str, *, limit: int = 34) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _scan_region_label(index: int, region: dict[str, Any]) -> str:
    return (
        f"{index:03d} {region.get('source', '?')}/{region.get('region', '?')}"
        f"{_measure_region_suffix(region)} bbox={_bbox_text(region.get('bbox'))}"
    )


def _scan_region_colour(region: dict[str, Any]) -> tuple[int, int, int]:
    source = str(region.get("source") or "")
    name = str(region.get("region") or "")
    if source == "page_ocr" or name == "page":
        return SCAN_PAGE_COLOUR
    if name == "row_system":
        return SCAN_ROW_COLOUR
    if name in {"root", "root_anchor_scan"}:
        return SCAN_ROOT_COLOUR
    if name == "root_accidental":
        return SCAN_ACCIDENTAL_COLOUR
    if name == "suffix_lower_right":
        return SCAN_SUFFIX_COLOUR
    if name == "slash_bass_below_root":
        return SCAN_SLASH_BASS_COLOUR
    return SCAN_PAGE_COLOUR


def _visible_debug_scan_region(region: dict[str, Any]) -> bool:
    return str(region.get("region") or "") in {
        "root_accidental",
        "suffix_lower_right",
    }


def _token_lookup(tokens: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    lookup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for token in tokens:
        lookup[_token_key(token)] = token
    return lookup


def _token_key(token: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(token.get("source") or ""),
        str(token.get("text") or token.get("text_raw") or ""),
        _bbox_key(token.get("bbox")),
    )


def _ocr_raw_text(token: dict[str, Any]) -> str:
    debug = token.get("debug")
    if not isinstance(debug, dict):
        return str(token.get("text") or "")

    normalization = debug.get("visual_normalization")
    if not isinstance(normalization, dict):
        return str(token.get("text") or "")

    raw_text = normalization.get("raw_text")
    if raw_text is None:
        return str(token.get("text") or "")
    return str(raw_text)


def _bbox_key(bbox: object) -> tuple[float, ...]:
    if not _valid_bbox(bbox):
        return ()
    return tuple(round(float(value), 1) for value in bbox)  # type: ignore[arg-type]


def _token_to_dict(token: Any) -> dict[str, Any]:
    if hasattr(token, "to_dict"):
        return token.to_dict()
    if isinstance(token, dict):
        return token
    return {
        "text": str(getattr(token, "text", "")),
        "bbox": list(getattr(token, "bbox", [])),
        "confidence": getattr(token, "confidence", None),
        "source": getattr(token, "source", None),
    }


def _iter_measures(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        measure
        for page in pages
        for system in page.get("systems") or []
        for measure in system.get("measures") or []
    ]


def _final_measure_label(measure: dict[str, Any]) -> str:
    index = measure.get("index", "?")
    chord_labels = []
    for chord in measure.get("chords") or []:
        raw = str(chord.get("text_raw") or "")
        norm = str(chord.get("text_norm") or raw or "")
        chord_labels.append(f"{raw}->{norm}" if raw and raw != norm else norm)

    resolved_labels = []
    for chord in measure.get("resolved_chords") or []:
        raw = str(chord.get("text_raw") or "")
        norm = str(chord.get("text_norm") or raw or "")
        resolved_labels.append(f"{raw}->{norm}" if raw and raw != norm else norm)

    symbol_labels = [
        str(symbol.get("type") or "?") for symbol in measure.get("symbols") or []
    ]
    final = ", ".join(chord_labels) if chord_labels else "-"
    if resolved_labels and not chord_labels:
        final = f"resolved: {', '.join(resolved_labels)}"
    if symbol_labels:
        final = f"{final} symbols: {', '.join(symbol_labels)}"
    return f"m{int(index):02d} final={final} bbox={_bbox_text(measure.get('bbox'))}"


def _measure_region_suffix(payload: dict[str, Any]) -> str:
    parts = []
    if payload.get("measure_index") is not None:
        parts.append(f"m{int(payload['measure_index']):02d}")
    if payload.get("row_index") is not None:
        parts.append(f"row={payload['row_index']}")
    if payload.get("col_index") is not None:
        parts.append(f"col={payload['col_index']}")
    if payload.get("region") is not None:
        parts.append(f"region={payload['region']}")
    return f" ({', '.join(parts)})" if parts else ""


def _maybe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _confidence(payload: dict[str, Any]) -> str:
    value = payload.get("confidence")
    if value is None:
        value = payload.get("conf")
    if not isinstance(value, int | float):
        return "-"
    return f"{float(value):.2f}"


def _bbox_text(bbox: object) -> str:
    if not _valid_bbox(bbox):
        return "[]"
    x0, y0, x1, y1 = [int(round(float(value))) for value in bbox]  # type: ignore[arg-type]
    return f"[{x0},{y0},{x1},{y1}]"


def _wrapped_panel_lines(lines: list[_PanelLine]) -> list[_PanelLine]:
    wrapped: list[_PanelLine] = []
    for line in lines:
        if not line.text:
            wrapped.append(line)
            continue
        chunks = textwrap.wrap(line.text, width=118) or [line.text]
        for index, chunk in enumerate(chunks):
            text = chunk if index == 0 else f"  {chunk}"
            wrapped.append(
                _PanelLine(
                    text=text,
                    colour=line.colour,
                    scale=line.scale,
                    thickness=line.thickness,
                )
            )
    return wrapped


def _draw_panel_lines(
    image: np.ndarray,
    lines: list[_PanelLine],
    *,
    x: int,
    y: int,
    line_height: int,
) -> None:
    for index, line in enumerate(lines):
        cv2.putText(
            image,
            line.text,
            (x, y + index * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            line.scale,
            line.colour,
            line.thickness,
            cv2.LINE_AA,
        )


def _draw_box(
    image: np.ndarray,
    bbox: object,
    colour: tuple[int, int, int],
    *,
    thickness: int,
) -> None:
    if not _valid_bbox(bbox):
        return
    x0, y0, x1, y1 = [int(round(float(value))) for value in bbox]
    cv2.rectangle(image, (x0, y0), (x1, y1), colour, thickness)


def _draw_text(
    image: np.ndarray,
    text: str,
    bbox: object,
    colour: tuple[int, int, int],
) -> None:
    if not text or not _valid_bbox(bbox):
        return
    x0, y0, _x1, _y1 = [int(round(float(value))) for value in bbox]
    cv2.putText(
        image,
        text,
        (x0 + 4, max(16, y0 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        colour,
        2,
        cv2.LINE_AA,
    )


def _draw_label_box(
    image: np.ndarray,
    text: str,
    bbox: object,
    colour: tuple[int, int, int],
    *,
    position: str,
) -> None:
    if not text or not _valid_bbox(bbox):
        return
    x0, y0, x1, y1 = [int(round(float(value))) for value in bbox]
    text_width, _text_height = _label_text_size(text)
    if position == "inside":
        label_x = x0 + 3
        label_y = y0 + 18
    elif position == "above":
        label_x = x0 + 3
        label_y = y0 - 5
    elif position == "below":
        label_x = x0 + 3
        label_y = y1 + 17
    elif position == "right":
        label_x = x1 + 8
        label_y = int((y0 + y1) / 2)
    elif position == "left_top":
        label_x = x0 - text_width - 10
        label_y = y0 + 17
    else:
        label_x = x0 + 3
        label_y = y0 - 5
        if label_y < 16:
            label_y = y1 + 17
    _draw_label_at(image, text, x=label_x, y=label_y, colour=colour)


def _label_text_size(text: str) -> tuple[int, int]:
    (text_width, text_height), _baseline = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        1,
    )
    return text_width, text_height


def _draw_label_at(
    image: np.ndarray,
    text: str,
    *,
    x: int,
    y: int,
    colour: tuple[int, int, int],
    fill: tuple[int, int, int] = (255, 255, 255),
) -> None:
    if not text:
        return
    height, width = image.shape[:2]
    scale = 0.42
    thickness = 1
    (text_width, text_height), baseline = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        thickness,
    )
    x = max(0, min(width - text_width - 4, x))
    y = max(text_height + 3, min(height - baseline - 2, y))
    pad = 3
    cv2.rectangle(
        image,
        (x - pad, y - text_height - pad),
        (x + text_width + pad, y + baseline + pad),
        fill,
        -1,
    )
    cv2.rectangle(
        image,
        (x - pad, y - text_height - pad),
        (x + text_width + pad, y + baseline + pad),
        colour,
        1,
    )
    cv2.putText(
        image,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        colour,
        thickness,
        cv2.LINE_AA,
    )


def _valid_bbox(bbox: object) -> bool:
    return (
        isinstance(bbox, list | tuple)
        and len(bbox) == 4
        and all(isinstance(value, int | float) for value in bbox)
    )
