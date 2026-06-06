from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import textwrap
from typing import Any

import cv2
import numpy as np


CHORD_CHART_OVERLAY_FILENAME = "chord_chart_overlay.png"
CHORD_CHART_OCR_DEBUG_OVERLAY_FILENAME = "chord_chart_ocr_debug_overlay.png"
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
    for region in scan_regions:
        _draw_box(
            marked_image,
            region.get("bbox"),
            _scan_region_colour(region),
            thickness=2,
        )

    _draw_final_measure_boxes(marked_image, pages, draw_labels=True)
    _draw_ocr_token_labels(
        marked_image,
        chart_ocr=chart_ocr,
        ocr_tokens=ocr_tokens,
        ocr_rejects=ocr_rejects,
    )
    _draw_debug_legend(marked_image)
    return marked_image


def _draw_final_measure_boxes(
    image: np.ndarray,
    pages: list[dict[str, Any]],
    *,
    draw_labels: bool = False,
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
                for chord in measure.get("chords") or []:
                    _draw_box(image, chord.get("bbox"), CHORD_COLOUR, thickness=3)


def _draw_ocr_token_labels(
    image: np.ndarray,
    *,
    chart_ocr: dict[str, Any],
    ocr_tokens: list[Any],
    ocr_rejects: list[dict[str, Any]],
) -> None:
    accepted_lookup = _token_lookup(chart_ocr.get("accepted_tokens") or [])
    unassigned_lookup = _token_lookup(chart_ocr.get("unassigned_tokens") or [])
    for token in ocr_tokens:
        token_dict = _token_to_dict(token)
        key = _token_key(token_dict)
        accepted = accepted_lookup.get(key)
        unassigned = unassigned_lookup.get(key)
        colour = OCR_ACCEPTED_COLOUR if accepted is not None else PANEL_MUTED_COLOUR
        _draw_box(image, token_dict.get("bbox"), colour, thickness=2)
        _draw_label_box(
            image,
            _ocr_token_display_label(
                token_dict,
                accepted=accepted,
                unassigned=unassigned,
            ),
            token_dict.get("bbox"),
            colour,
            position="above",
        )

    for reject in ocr_rejects:
        _draw_box(image, reject.get("bbox"), OCR_REJECTED_COLOUR, thickness=2)
        _draw_label_box(
            image,
            _rejected_token_display_label(reject),
            reject.get("bbox"),
            OCR_REJECTED_COLOUR,
            position="below",
        )


def _draw_debug_legend(image: np.ndarray) -> None:
    lines = [
        "scan: grey page, teal row, blue root, purple accidental, orange suffix",
        "tokens: green accepted/corrected, grey unassigned, red rejected",
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
            "Legend: grey=page/measure, teal=row scan, blue=root, purple=accidental, orange=suffix, green=OCR hit, red=reject",
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
        raw = str(token_dict.get("text") or "")
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
    if name == "root":
        return SCAN_ROOT_COLOUR
    if name == "root_accidental":
        return SCAN_ACCIDENTAL_COLOUR
    if name == "suffix_lower_right":
        return SCAN_SUFFIX_COLOUR
    if name == "slash_bass_below_root":
        return SCAN_SLASH_BASS_COLOUR
    return SCAN_PAGE_COLOUR


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
    x0, y0, _x1, y1 = [int(round(float(value))) for value in bbox]
    if position == "inside":
        label_y = y0 + 18
    elif position == "below":
        label_y = y1 + 17
    else:
        label_y = y0 - 5
        if label_y < 16:
            label_y = y1 + 17
    _draw_label_at(image, text, x=x0 + 3, y=label_y, colour=colour)


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
