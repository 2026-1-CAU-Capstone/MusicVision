from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.chord_charts.ocr_backend import (
    _cell_ocr_regions,
    chart_cell_ocr_region_boxes,
)
from pipeline.chord_charts.parser import detect_chart_grid
from pipeline.chords.ocr_common import load_rgb_image


DEFAULT_REGIONS = ("root", "root_accidental", "suffix_lower_right")
REGION_COLOURS = {
    "full": (120, 120, 120),
    "top": (0, 150, 180),
    "bottom": (60, 160, 80),
    "left": (160, 100, 40),
    "right": (40, 100, 160),
    "low": (180, 120, 40),
    "root": (30, 110, 235),
    "root_accidental": (155, 80, 210),
    "suffix_lower_right": (235, 130, 20),
    "root_anchor_scan": (30, 110, 235),
    "root_wide": (30, 110, 235),
    "root_accidental_wide": (155, 80, 210),
    "suffix_wide": (235, 130, 20),
    "slash_bass_below_root": (30, 170, 155),
}
MEASURE_COLOUR = (70, 70, 70)


def main() -> None:
    args = _parse_args()
    image_path = args.image.resolve()
    output_dir = args.output_dir or _default_output_dir(image_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    image = load_rgb_image(image_path)
    rows = detect_chart_grid(image)
    if not rows:
        raise SystemExit(f"No chart grid detected in {image_path}")

    region_names = _parse_regions(args.regions)
    measure_indices = _parse_measure_indices(args.measure_indices)
    scan_boxes = chart_cell_ocr_region_boxes(
        image,
        rows,
        measure_indices=measure_indices,
        region_names=region_names,
        source="crop_preview",
    )
    measure_boxes = _measure_boxes(image, rows, measure_indices=measure_indices)

    combined = image.copy()
    if not args.no_measure_boxes:
        _draw_measure_boxes(combined, measure_boxes)
    _draw_scan_boxes(combined, scan_boxes, draw_labels=args.labels)
    combined_path = output_dir / "crop_regions_combined.png"
    _write_rgb_png(combined_path, combined)

    per_region_paths = []
    for region_name in region_names:
        overlay = image.copy()
        if not args.no_measure_boxes:
            _draw_measure_boxes(overlay, measure_boxes)
        region_boxes = [box for box in scan_boxes if box.get("region") == region_name]
        _draw_scan_boxes(overlay, region_boxes, draw_labels=args.labels)
        output_path = output_dir / f"crop_regions_{_safe_name(region_name)}.png"
        _write_rgb_png(output_path, overlay)
        per_region_paths.append(output_path)

    summary_path = output_dir / "crop_regions_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "image_path": str(image_path),
                "output_dir": str(output_dir.resolve()),
                "row_count": len(rows),
                "measure_count": len(_measure_boxes(image, rows, measure_indices=None)),
                "previewed_measure_indices": (
                    sorted(measure_indices) if measure_indices is not None else "all"
                ),
                "region_names": list(region_names),
                "region_definitions": [
                    {
                        "name": name,
                        "x_start_ratio": xa,
                        "x_end_ratio": xb,
                        "y_start_ratio": ya,
                        "y_end_ratio": yb,
                    }
                    for name, xa, xb, ya, yb in _cell_ocr_regions()
                    if name in set(region_names)
                ],
                "scan_box_count": len(scan_boxes),
                "combined_overlay": combined_path.name,
                "per_region_overlays": [path.name for path in per_region_paths],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {combined_path}")
    for path in per_region_paths:
        print(f"Wrote {path}")
    print(f"Wrote {summary_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render chord-chart crop-region geometry without running OCR. "
            "Edit _cell_ocr_regions() in pipeline/chord_charts/ocr_backend.py, "
            "rerun this script, and refresh the generated PNG."
        )
    )
    parser.add_argument("image", type=Path, help="Chord-chart image to preview.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for preview PNGs. Defaults to storage/jobs/crop-region-preview/<image-name>.",
    )
    parser.add_argument(
        "--regions",
        default="active",
        help=(
            "Comma-separated region names, 'active' for production selective crops, "
            "or 'all'. Default: active."
        ),
    )
    parser.add_argument(
        "--measure-indices",
        help="Optional comma/range list such as '1,3,8-12'. Defaults to all measures.",
    )
    parser.add_argument(
        "--labels",
        action="store_true",
        help="Draw small measure/region labels on the image.",
    )
    parser.add_argument(
        "--no-measure-boxes",
        action="store_true",
        help="Only draw crop boxes, not the full measure cells.",
    )
    return parser.parse_args()


def _parse_regions(value: str) -> tuple[str, ...]:
    normalized = value.strip()
    if normalized == "active":
        return DEFAULT_REGIONS
    all_regions = tuple(region[0] for region in _cell_ocr_regions())
    if normalized == "all":
        return all_regions

    requested = tuple(part.strip() for part in normalized.split(",") if part.strip())
    unknown = sorted(set(requested) - set(all_regions))
    if unknown:
        raise SystemExit(f"Unknown crop region(s): {', '.join(unknown)}")
    if not requested:
        raise SystemExit("At least one crop region is required.")
    return requested


def _parse_measure_indices(value: str | None) -> set[int] | None:
    if value is None:
        return None

    indices: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise SystemExit(f"Invalid measure range: {part}")
            indices.update(range(start, end + 1))
        else:
            indices.add(int(part))

    return indices


def _default_output_dir(image_path: Path) -> Path:
    return Path("storage") / "jobs" / "crop-region-preview" / image_path.stem


def _measure_boxes(
    image: np.ndarray,
    rows: list[Any],
    *,
    measure_indices: set[int] | None,
) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    row_list = list(rows)
    height, width = image.shape[:2]
    measure_index = 1
    for row_position, row in enumerate(row_list):
        boundaries = getattr(row, "boundaries", [])
        next_y_top = (
            float(getattr(row_list[row_position + 1], "y_top"))
            if row_position + 1 < len(row_list)
            else float(height)
        )
        for col_index, (left, right) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            if measure_indices is not None and measure_index not in measure_indices:
                measure_index += 1
                continue

            x0 = int(max(0, float(left.x) + 8))
            x1 = int(min(width, float(right.x) - 8))
            y0 = int(max(0, float(row.y_top) - 35))
            y1 = int(min(height, next_y_top - 8, float(row.y_bottom) + 80))
            if x1 > x0 and y1 > y0:
                boxes.append(
                    {
                        "measure_index": measure_index,
                        "row_index": getattr(row, "index", None),
                        "col_index": col_index,
                        "bbox": [float(x0), float(y0), float(x1), float(y1)],
                    }
                )
            measure_index += 1
    return boxes


def _draw_measure_boxes(image: np.ndarray, boxes: list[dict[str, Any]]) -> None:
    for box in boxes:
        _draw_box(image, box["bbox"], MEASURE_COLOUR, thickness=1)


def _draw_scan_boxes(
    image: np.ndarray,
    boxes: list[dict[str, Any]],
    *,
    draw_labels: bool,
) -> None:
    for box in boxes:
        colour = REGION_COLOURS.get(str(box.get("region")), (120, 120, 120))
        _draw_box(image, box["bbox"], colour, thickness=2)
        if draw_labels:
            _draw_label(
                image,
                f"m{box.get('measure_index')} {box.get('region')}",
                box["bbox"],
                colour,
            )


def _draw_box(
    image: np.ndarray,
    bbox: list[float],
    colour: tuple[int, int, int],
    *,
    thickness: int,
) -> None:
    x0, y0, x1, y1 = [int(round(value)) for value in bbox]
    cv2.rectangle(image, (x0, y0), (x1, y1), colour, thickness)


def _draw_label(
    image: np.ndarray,
    text: str,
    bbox: list[float],
    colour: tuple[int, int, int],
) -> None:
    x0, y0, _x1, _y1 = [int(round(value)) for value in bbox]
    cv2.putText(
        image,
        text,
        (x0 + 4, max(16, y0 - 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        colour,
        1,
        cv2.LINE_AA,
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "region"


def _write_rgb_png(path: Path, image: np.ndarray) -> None:
    cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
