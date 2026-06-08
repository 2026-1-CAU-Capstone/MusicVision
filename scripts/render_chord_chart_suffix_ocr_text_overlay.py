from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.chord_charts.image_preprocessing import upscale_small_chord_chart_image
from pipeline.chord_charts.ocr_backend import (
    CHART_SEMANTIC_REGION_ALLOWLISTS,
    RootAnchorCandidate,
    extract_chart_cell_ocr_tokens,
    extract_chart_root_anchor_local_ocr_tokens,
)
from pipeline.chord_charts.parser import detect_chart_grid
from pipeline.chords.ocr_common import load_rgb_image


OVERLAY_FILENAME = "chord_chart_suffix_ocr_text_overlay.png"
JSON_FILENAME = "chord_chart_suffix_ocr_text_overlay.json"


def main() -> None:
    args = _parse_args()
    job_dir = args.job_dir.resolve()
    output_dir = job_dir / "output"
    debug_path = output_dir / "chord_chart_debug.json"
    image_path = args.image or (job_dir / "intermediate" / "preprocessed.jpg")

    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    image = upscale_small_chord_chart_image(load_rgb_image(image_path)).image
    rows = detect_chart_grid(image)
    if not rows:
        raise SystemExit("No chart grid detected.")

    core_tokens, core_rejects = extract_chart_cell_ocr_tokens(
        image,
        rows,
        region_names=("suffix_lower_right",),
        region_allowlists=CHART_SEMANTIC_REGION_ALLOWLISTS,
        source="cell_ocr_semantic_suffix_probe",
    )

    anchors = _anchor_candidates_from_debug(debug)
    anchor_tokens, anchor_rejects = extract_chart_root_anchor_local_ocr_tokens(
        image,
        rows,
        anchor_candidates=anchors,
        measure_indices={anchor.measure_index for anchor in anchors},
        region_allowlists=CHART_SEMANTIC_REGION_ALLOWLISTS,
        source="cell_ocr_root_anchor_suffix_probe",
    )
    anchor_tokens = [
        token for token in anchor_tokens if token.region == "suffix_lower_right"
    ]
    anchor_rejects = [
        reject
        for reject in anchor_rejects
        if reject.get("region") == "suffix_lower_right"
    ]

    records = _suffix_records(
        core_tokens=[token.to_dict() for token in core_tokens],
        core_rejects=core_rejects,
        anchor_tokens=[token.to_dict() for token in anchor_tokens],
        anchor_rejects=anchor_rejects,
    )

    overlay_path = output_dir / OVERLAY_FILENAME
    json_path = output_dir / JSON_FILENAME
    _write_overlay(image=image, records=records, output_path=overlay_path)
    json_path.write_text(
        json.dumps({"overlay": str(overlay_path), "records": records}, indent=2),
        encoding="utf-8",
    )

    print(f"wrote {overlay_path}")
    print(f"wrote {json_path}")
    print(
        "records="
        f"{len(records)} core_tokens={len(core_tokens)} "
        f"core_rejects={len(core_rejects)} anchor_tokens={len(anchor_tokens)} "
        f"anchor_rejects={len(anchor_rejects)}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a text overlay for chord-chart suffix OCR reads."
    )
    parser.add_argument(
        "--job-dir",
        type=Path,
        required=True,
        help="Job directory containing output/chord_chart_debug.json.",
    )
    parser.add_argument(
        "--image",
        type=Path,
        help="Optional preprocessed image path. Defaults to job/intermediate/preprocessed.jpg.",
    )
    return parser.parse_args()


def _anchor_candidates_from_debug(debug: dict[str, Any]) -> list[RootAnchorCandidate]:
    strategy = debug.get("chart_ocr", {}).get("strategy", {})
    anchors = []
    for item in strategy.get("multi_chord_anchor_candidates") or []:
        anchors.append(
            RootAnchorCandidate(
                measure_index=int(item["measure_index"]),
                anchor_index=int(item["anchor_index"]),
                root=str(item.get("root") or "?"),
                center_x=float(item["center_x"]),
                bbox=tuple(float(value) for value in item["bbox"]),
                confidence=(
                    None
                    if item.get("confidence") is None
                    else float(item["confidence"])
                ),
                source_text=str(item.get("source_text") or ""),
                source_bbox=tuple(
                    float(value) for value in item.get("source_bbox") or item["bbox"]
                ),
                row_index=item.get("row_index"),
                col_index=item.get("col_index"),
                source_kind=item.get("source_kind"),
            )
        )
    return anchors


def _suffix_records(
    *,
    core_tokens: list[dict[str, Any]],
    core_rejects: list[dict[str, Any]],
    anchor_tokens: list[dict[str, Any]],
    anchor_rejects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    groups = [
        ("core", "accepted", core_tokens),
        ("core", "rejected", core_rejects),
        ("anchor", "accepted", anchor_tokens),
        ("anchor", "rejected", anchor_rejects),
    ]
    for source_kind, status, values in groups:
        for value in values:
            debug_info = value.get("debug") or {}
            visual = debug_info.get("visual_normalization") or {}
            root_anchor = debug_info.get("root_anchor") or {}
            records.append(
                {
                    "source_kind": source_kind,
                    "status": status,
                    "measure_index": value.get("measure_index"),
                    "anchor_index": root_anchor.get("anchor_index"),
                    "text": value.get("text"),
                    "raw_text": visual.get("raw_text", value.get("text")),
                    "normalized_text": visual.get(
                        "normalized_text", value.get("text")
                    ),
                    "confidence": value.get("confidence"),
                    "bbox": value.get("bbox"),
                    "reason": value.get("reason"),
                    "debug": debug_info,
                }
            )
    records.sort(
        key=lambda record: (
            record.get("measure_index") or 0,
            record.get("anchor_index") or 0,
            record.get("source_kind") or "",
            record.get("bbox") or [],
        )
    )
    return records


def _write_overlay(
    *,
    image: Any,
    records: list[dict[str, Any]],
    output_path: Path,
) -> None:
    overlay = cv2.cvtColor(image.copy(), cv2.COLOR_RGB2BGR)
    accepted_color = (0, 140, 255)
    anchor_color = (255, 0, 180)
    rejected_color = (40, 40, 230)
    text_bg = (255, 255, 255)
    text_fg = (0, 0, 0)
    font = cv2.FONT_HERSHEY_SIMPLEX

    legend = [
        "suffix OCR text overlay (current boundaries)",
        "orange core accepted | magenta anchor-local accepted | red rejected",
        "label: measure[/anchor] raw -> normalized confidence",
    ]
    _draw_legend(
        overlay,
        legend=legend,
        font=font,
        text_bg=text_bg,
        text_fg=text_fg,
    )

    for record in records:
        bbox = record.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = [int(round(float(value))) for value in bbox]
        source_kind = record.get("source_kind")
        color = (
            rejected_color
            if record.get("status") == "rejected"
            else anchor_color
            if source_kind == "anchor"
            else accepted_color
        )
        cv2.rectangle(
            overlay,
            (x0, y0),
            (x1, y1),
            color,
            3 if source_kind == "anchor" else 2,
        )
        _draw_record_label(
            overlay,
            record=record,
            bbox=(x0, y0, x1, y1),
            color=color,
            font=font,
            text_bg=text_bg,
            text_fg=text_fg,
        )

    cv2.imwrite(str(output_path), overlay)


def _draw_legend(
    overlay: Any,
    *,
    legend: list[str],
    font: int,
    text_bg: tuple[int, int, int],
    text_fg: tuple[int, int, int],
) -> None:
    legend_scale = 0.48
    legend_thickness = 1
    legend_w = 0
    legend_h = 14
    for line in legend:
        (tw, th), _ = cv2.getTextSize(
            line,
            font,
            legend_scale,
            legend_thickness,
        )
        legend_w = max(legend_w, tw)
        legend_h += th + 10
    cv2.rectangle(overlay, (4, 4), (legend_w + 16, legend_h), text_bg, -1)
    cv2.rectangle(overlay, (4, 4), (legend_w + 16, legend_h), (80, 80, 80), 1)
    y = 22
    for line in legend:
        cv2.putText(
            overlay,
            line,
            (10, y),
            font,
            legend_scale,
            text_fg,
            legend_thickness,
            cv2.LINE_AA,
        )
        y += 22


def _draw_record_label(
    overlay: Any,
    *,
    record: dict[str, Any],
    bbox: tuple[int, int, int, int],
    color: tuple[int, int, int],
    font: int,
    text_bg: tuple[int, int, int],
    text_fg: tuple[int, int, int],
) -> None:
    x0, y0, _x1, _y1 = bbox
    measure = record.get("measure_index")
    anchor = record.get("anchor_index")
    prefix = f"m{int(measure):02d}" if measure is not None else "m??"
    if anchor is not None:
        prefix += f"/a{int(anchor)}"
    conf = record.get("confidence")
    conf_text = "?" if conf is None else f"{float(conf):.2f}"
    label = (
        f"{prefix} {_ascii_label(record.get('raw_text'))}->"
        f"{_ascii_label(record.get('normalized_text'))} {conf_text}"
    )
    (tw, th), _ = cv2.getTextSize(label, font, 0.43, 1)
    label_x = max(0, min(x0, overlay.shape[1] - tw - 8))
    label_y = max(18, y0 - 6)
    cv2.rectangle(
        overlay,
        (label_x, label_y - th - 6),
        (label_x + tw + 6, label_y + 4),
        text_bg,
        -1,
    )
    cv2.rectangle(
        overlay,
        (label_x, label_y - th - 6),
        (label_x + tw + 6, label_y + 4),
        color,
        1,
    )
    cv2.putText(
        overlay,
        label,
        (label_x + 3, label_y),
        font,
        0.43,
        text_fg,
        1,
        cv2.LINE_AA,
    )


def _ascii_label(value: object) -> str:
    text = str(value or "")
    return (
        text.replace("\u25b3", "tri")
        .replace("\u2206", "tri")
        .replace("\u0394", "tri")
        .replace("\u00f8", "halfdim")
        .replace("\u266d", "b")
        .replace("\u266f", "#")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


if __name__ == "__main__":
    main()
