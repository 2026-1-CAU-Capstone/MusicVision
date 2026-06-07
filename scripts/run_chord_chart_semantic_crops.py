from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.chord_charts.ocr_backend import (
    CHART_SEMANTIC_REGION_ALLOWLISTS,
    MULTI_CHORD_CHART_CELL_REGION_NAMES,
    SEMANTIC_CHART_CELL_REGION_NAMES,
    _cell_ocr_regions,
    build_root_anchor_candidates,
    chart_cell_ocr_region_boxes,
    chart_root_anchor_local_region_boxes,
    detect_visual_root_anchor_candidates,
    extract_chart_cell_ocr_tokens,
    extract_chart_ocr_tokens,
    extract_chart_root_anchor_local_ocr_tokens,
    measure_indices_with_multiple_root_anchors,
)
from pipeline.chord_charts.image_preprocessing import upscale_small_chord_chart_image
from pipeline.chord_charts.overlay import (
    write_chord_chart_ocr_debug_overlay,
    write_chord_chart_overlay,
    write_chord_chart_root_ocr_bbox_overlay,
    write_chord_chart_scan_boundary_overlay,
)
from pipeline.chord_charts.ocr_strategy import (
    plan_multi_chord_chart_cell_ocr,
    root_anchor_hints_from_plan,
)
from pipeline.chord_charts.parser import detect_chart_grid, parse_chord_chart_image
from pipeline.chord_charts.public_payload import build_public_chord_chart_payload
from pipeline.chord_charts.semantic_assembly import assemble_semantic_chord_tokens
from pipeline.chords.ocr_common import load_rgb_image
from pipeline.export import export_chord_chart_debug_json, export_chord_chart_json
from pipeline.preprocess import preprocess_input


def main() -> None:
    args = _parse_args()
    start_time = time.perf_counter()
    input_path = args.image.resolve()
    job_id = args.job_id or _default_job_id(input_path)
    job_dir = args.job_dir or Path("storage") / "jobs" / job_id
    intermediate_dir = job_dir / "intermediate"
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"job_id={job_id}")
    print(f"input={input_path}")

    preprocessed_input_path = preprocess_input(
        input_file_path=input_path,
        intermediate_dir=intermediate_dir,
    )
    image = load_rgb_image(preprocessed_input_path)
    image_scale = upscale_small_chord_chart_image(image)
    image = image_scale.image
    if image_scale.scale != 1.0:
        print(
            "upscaled image: "
            f"{image_scale.original_width}x{image_scale.original_height} -> "
            f"{image_scale.width}x{image_scale.height} "
            f"({image_scale.scale:.2f}x)"
        )
    rows = detect_chart_grid(image)
    if not rows:
        raise SystemExit("No chord-chart grid was detected.")

    semantic_mode = args.regions.strip() == "semantic"
    region_names = _parse_regions(args.regions)
    measure_indices = _parse_measure_indices(args.measure_indices)
    allowlists = None if args.no_allowlists else CHART_SEMANTIC_REGION_ALLOWLISTS
    expected_core_cell_ocr_calls = _count_expected_cell_calls(
        rows,
        region_count=len(region_names),
        measure_indices=measure_indices,
    )

    page_tokens = []
    page_rejects = []
    page_runtime = 0.0
    if not args.no_page_ocr:
        print("running page OCR...")
        page_start = time.perf_counter()
        page_tokens, page_rejects = extract_chart_ocr_tokens(image)
        page_runtime = time.perf_counter() - page_start
        print(
            "page OCR: "
            f"{len(page_tokens)} accepted, {len(page_rejects)} rejected "
            f"in {page_runtime:.2f}s"
        )

    repeat_measure_indices: set[int] = set()
    if page_tokens:
        repeat_probe_payload = parse_chord_chart_image(
            image=image,
            tokens=page_tokens,
            ocr_rejects=page_rejects,
            job_id=f"{job_id}-repeat-probe",
            source_file=input_path.name,
            rows=rows,
        )
        repeat_measure_indices = _repeat_measure_indices_from_payload(
            repeat_probe_payload
        )
        print(
            "repeat probe: "
            f"{len(repeat_measure_indices)} visual repeat candidate measure(s)"
        )

    multi_chord_plan = None
    supplemental_measure_indices: set[int] = set()
    visual_root_anchor_candidates = []
    visual_multi_chord_measure_indices: set[int] = set()
    visual_supplemental_measure_indices: set[int] = set()
    if semantic_mode:
        if page_tokens:
            multi_chord_plan = plan_multi_chord_chart_cell_ocr(
                rows=rows,
                page_tokens=page_tokens,
                row_tokens=[],
            )
            supplemental_measure_indices = set(multi_chord_plan.measure_indices)
            if measure_indices is not None:
                supplemental_measure_indices &= set(measure_indices)
        elif measure_indices is not None:
            supplemental_measure_indices = set(measure_indices)
        elif args.no_page_ocr:
            supplemental_measure_indices = _all_measure_indices(rows)
        visual_root_anchor_candidates = detect_visual_root_anchor_candidates(
            image,
            rows,
            measure_indices=measure_indices,
        )
        visual_multi_chord_measure_indices = measure_indices_with_multiple_root_anchors(
            visual_root_anchor_candidates
        )
        visual_supplemental_measure_indices = set(visual_multi_chord_measure_indices)
        if measure_indices is not None:
            visual_supplemental_measure_indices &= set(measure_indices)
        supplemental_measure_indices |= visual_supplemental_measure_indices
        if visual_multi_chord_measure_indices:
            print(
                "visual root anchors: "
                f"{len(visual_root_anchor_candidates)} candidate(s), "
                f"{len(visual_multi_chord_measure_indices)} multi-anchor measure(s), "
                f"{len(visual_supplemental_measure_indices)} supplemental measure(s)"
            )

    expected_root_anchor_probe_ocr_calls = _count_expected_cell_calls(
        rows,
        region_count=len(MULTI_CHORD_CHART_CELL_REGION_NAMES),
        measure_indices=supplemental_measure_indices,
    )
    expected_cell_ocr_calls = (
        expected_core_cell_ocr_calls + expected_root_anchor_probe_ocr_calls
    )
    print(
        "running semantic cell OCR: "
        f"{expected_cell_ocr_calls} calls "
        f"({expected_core_cell_ocr_calls} core, "
        f"{expected_root_anchor_probe_ocr_calls} root-anchor probe)..."
    )
    cell_start = time.perf_counter()
    last_progress_print = 0.0

    def report_cell_progress(completed: int, total: int) -> None:
        nonlocal last_progress_print
        now = time.perf_counter()
        if completed == total or now - last_progress_print >= 10.0:
            elapsed = now - cell_start
            print(f"cell OCR: {completed}/{total} regions in {elapsed:.2f}s")
            last_progress_print = now

    cell_tokens, cell_rejects = extract_chart_cell_ocr_tokens(
        image,
        rows,
        measure_indices=measure_indices,
        region_names=region_names,
        region_allowlists=allowlists,
        source="cell_ocr_semantic",
        progress_callback=report_cell_progress,
    )
    root_anchor_probe_tokens = []
    root_anchor_probe_rejects = []
    root_anchor_candidates = []
    root_anchor_local_tokens = []
    root_anchor_local_rejects = []
    root_anchor_local_ocr_calls = 0
    if supplemental_measure_indices:
        root_anchor_hints = (
            root_anchor_hints_from_plan(multi_chord_plan)
            if multi_chord_plan is not None
            else []
        )
        root_anchor_probe_tokens, root_anchor_probe_rejects = (
            extract_chart_cell_ocr_tokens(
                image,
                rows,
                measure_indices=supplemental_measure_indices,
                region_names=MULTI_CHORD_CHART_CELL_REGION_NAMES,
                region_allowlists=allowlists,
                source="cell_ocr_root_anchor_probe",
                progress_callback=report_cell_progress,
            )
        )
        cell_rejects.extend(root_anchor_probe_rejects)
        root_anchor_candidates = build_root_anchor_candidates(
            root_anchor_probe_tokens,
            image=image,
            rows=rows,
            measure_indices=supplemental_measure_indices,
            anchor_hints=root_anchor_hints,
            visual_candidates=visual_root_anchor_candidates,
        )
        root_anchor_local_boxes = chart_root_anchor_local_region_boxes(
            image,
            rows,
            anchor_candidates=root_anchor_candidates,
            measure_indices=supplemental_measure_indices,
            source="cell_ocr_root_anchor",
        )
        root_anchor_local_ocr_calls = len(root_anchor_local_boxes)
        if root_anchor_local_ocr_calls:
            print(
                "running root-anchor local OCR: "
                f"{root_anchor_local_ocr_calls} calls "
                f"from {len(root_anchor_candidates)} anchor(s)..."
            )
            root_anchor_local_tokens, root_anchor_local_rejects = (
                extract_chart_root_anchor_local_ocr_tokens(
                    image,
                    rows,
                    anchor_candidates=root_anchor_candidates,
                    measure_indices=supplemental_measure_indices,
                    region_allowlists=allowlists,
                    source="cell_ocr_root_anchor",
                    progress_callback=report_cell_progress,
                )
            )
            cell_tokens.extend(root_anchor_local_tokens)
            cell_rejects.extend(root_anchor_local_rejects)
    cell_runtime = time.perf_counter() - cell_start
    print(
        "semantic cell OCR: "
        f"{len(cell_tokens)} accepted, {len(cell_rejects)} rejected "
        f"in {cell_runtime:.2f}s"
    )
    assembly = assemble_semantic_chord_tokens(
        cell_tokens,
        image=image,
    )
    print(f"semantic assembly: {len(assembly.tokens)} chord tokens")

    result_payload = parse_chord_chart_image(
        image=image,
        tokens=[*page_tokens, *assembly.tokens],
        ocr_rejects=[*page_rejects, *cell_rejects],
        job_id=job_id,
        source_file=input_path.name,
        rows=rows,
    )
    result_payload["chart_ocr"]["strategy"] = {
        "mode": "page_semantic_cell_ocr"
        if not args.no_page_ocr
        else "semantic_cell_ocr_only",
        "page_ocr_enabled": not args.no_page_ocr,
        "page_tokens": len(page_tokens),
        "page_rejects": len(page_rejects),
        "page_runtime_seconds": round(page_runtime, 3),
        "row_ocr_enabled": False,
        "semantic_cell_tokens": len(cell_tokens),
        "semantic_cell_rejects": len(cell_rejects),
        "semantic_cell_runtime_seconds": round(cell_runtime, 3),
        "semantic_assembled_tokens": len(assembly.tokens),
        "repeat_probe_measure_indices": sorted(repeat_measure_indices),
        "semantic_assembly_skip_measure_indices": [],
        "semantic_cell_region_names": list(region_names),
        "semantic_cell_ocr_calls": expected_core_cell_ocr_calls,
        "semantic_cell_measure_indices": (
            sorted(measure_indices) if measure_indices is not None else "all"
        ),
        "multi_chord_supplemental_region_names": list(
            MULTI_CHORD_CHART_CELL_REGION_NAMES
        ),
        "multi_chord_supplemental_measure_indices": sorted(
            supplemental_measure_indices
        ),
        "multi_chord_supplemental_ocr_calls": expected_root_anchor_probe_ocr_calls,
        "multi_chord_supplemental_tokens": len(root_anchor_local_tokens),
        "multi_chord_supplemental_rejects": (
            len(root_anchor_probe_rejects) + len(root_anchor_local_rejects)
        ),
        "multi_chord_anchor_probe_tokens": len(root_anchor_probe_tokens),
        "multi_chord_anchor_probe_rejects": len(root_anchor_probe_rejects),
        "multi_chord_anchor_candidates": [
            anchor.to_dict() for anchor in root_anchor_candidates
        ],
        "multi_chord_visual_anchor_candidates": [
            anchor.to_dict() for anchor in visual_root_anchor_candidates
        ],
        "multi_chord_visual_anchor_measure_indices": sorted(
            visual_multi_chord_measure_indices
        ),
        "multi_chord_visual_supplemental_measure_indices": sorted(
            visual_supplemental_measure_indices
        ),
        "multi_chord_anchor_local_ocr_calls": root_anchor_local_ocr_calls,
        "multi_chord_anchor_local_tokens": len(root_anchor_local_tokens),
        "multi_chord_anchor_local_rejects": len(root_anchor_local_rejects),
        "multi_chord_supplemental_plan": (
            multi_chord_plan.diagnostics if multi_chord_plan is not None else None
        ),
        "region_allowlists_enabled": allowlists is not None,
        "region_allowlists": {
            region_name: allowlists.get(region_name)
            for region_name in region_names
            if allowlists is not None and allowlists.get(region_name) is not None
        },
        "semantic_assembly": assembly.diagnostics,
        "image_scaling": image_scale.to_dict(),
    }

    scan_regions: list[dict[str, Any]] = []
    if not args.no_page_ocr:
        scan_regions.append(
            {
                "source": "page_ocr",
                "region": "page",
                "bbox": [0.0, 0.0, float(image.shape[1]), float(image.shape[0])],
            }
        )
    scan_regions.extend(
        chart_cell_ocr_region_boxes(
            image,
            rows,
            measure_indices=measure_indices,
            region_names=region_names,
            source="cell_ocr_semantic",
        )
    )
    if supplemental_measure_indices:
        scan_regions.extend(
            chart_cell_ocr_region_boxes(
                image,
                rows,
                measure_indices=supplemental_measure_indices,
                region_names=MULTI_CHORD_CHART_CELL_REGION_NAMES,
                source="cell_ocr_root_anchor_probe",
            )
        )
        scan_regions.extend(
            chart_root_anchor_local_region_boxes(
                image,
                rows,
                anchor_candidates=root_anchor_candidates,
                measure_indices=supplemental_measure_indices,
                source="cell_ocr_root_anchor",
            )
        )

    overlay_path = write_chord_chart_overlay(
        image=image,
        pages=result_payload["pages"],
        output_dir=output_dir,
    )
    debug_overlay_path = write_chord_chart_ocr_debug_overlay(
        image=image,
        pages=result_payload["pages"],
        chart_ocr=result_payload["chart_ocr"],
        ocr_tokens=[
            *page_tokens,
            *root_anchor_probe_tokens,
            *cell_tokens,
            *assembly.tokens,
        ],
        ocr_rejects=[*page_rejects, *cell_rejects],
        scan_regions=scan_regions,
        output_dir=output_dir,
    )
    scan_boundary_overlay_path = write_chord_chart_scan_boundary_overlay(
        image=image,
        pages=result_payload["pages"],
        scan_regions=scan_regions,
        chart_ocr=result_payload["chart_ocr"],
        output_dir=output_dir,
    )
    root_ocr_bbox_overlay_path = write_chord_chart_root_ocr_bbox_overlay(
        image=image,
        pages=result_payload["pages"],
        chart_ocr=result_payload["chart_ocr"],
        output_dir=output_dir,
    )
    result_payload["overlay_file"] = overlay_path.name
    result_payload["debug_overlay_file"] = debug_overlay_path.name
    result_payload["scan_boundary_overlay_file"] = scan_boundary_overlay_path.name
    result_payload["root_ocr_bbox_overlay_file"] = root_ocr_bbox_overlay_path.name
    result_payload["chart_ocr"]["debug_overlay_file"] = debug_overlay_path.name
    result_payload["chart_ocr"]["scan_boundary_overlay_file"] = (
        scan_boundary_overlay_path.name
    )
    result_payload["chart_ocr"]["root_ocr_bbox_overlay_file"] = (
        root_ocr_bbox_overlay_path.name
    )

    chord_chart_debug_path = export_chord_chart_debug_json(
        result_payload=result_payload,
        output_dir=output_dir,
    )
    public_payload = build_public_chord_chart_payload(result_payload)
    chord_chart_path = export_chord_chart_json(
        result_payload=public_payload,
        output_dir=output_dir,
    )

    runtime_seconds = time.perf_counter() - start_time
    summary_path = job_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "input_file": str(args.image),
                "runtime_seconds": round(runtime_seconds, 2),
                "page_runtime_seconds": round(page_runtime, 2),
                "semantic_cell_runtime_seconds": round(cell_runtime, 2),
                "image_scaling": image_scale.to_dict(),
                "chord_chart_path": str(chord_chart_path),
                "chord_chart_debug_path": str(chord_chart_debug_path),
                "debug_overlay_path": str(debug_overlay_path),
                "scan_boundary_overlay_path": str(scan_boundary_overlay_path),
                "root_ocr_bbox_overlay_path": str(root_ocr_bbox_overlay_path),
                "public_chord_count": len(public_payload.get("chords") or []),
                "public_measure_count": public_payload.get("measure_count"),
                "public_flow": public_payload.get("flow"),
                "public_chords": public_payload.get("chords") or [],
                "strategy": result_payload["chart_ocr"]["strategy"],
                "crop_regions": [
                    {
                        "name": name,
                        "x_start_ratio": xa,
                        "x_end_ratio": xb,
                        "y_start_ratio": ya,
                        "y_end_ratio": yb,
                    }
                    for name, xa, xb, ya, yb in _cell_ocr_regions()
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote {chord_chart_path}")
    print(f"wrote {chord_chart_debug_path}")
    print(f"wrote {debug_overlay_path}")
    print(f"wrote {scan_boundary_overlay_path}")
    print(f"wrote {root_ocr_bbox_overlay_path}")
    print(f"wrote {summary_path}")
    print(f"runtime={runtime_seconds:.2f}s")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an experimental chord-chart OCR strategy: page OCR plus "
            "allowlisted semantic cell crops for every selected measure."
        )
    )
    parser.add_argument("image", type=Path, help="Chord-chart image to process.")
    parser.add_argument("--job-id", help="Optional explicit storage job id.")
    parser.add_argument(
        "--job-dir",
        type=Path,
        help="Optional explicit output job directory.",
    )
    parser.add_argument(
        "--regions",
        default="semantic",
        help=(
            "Comma-separated crop regions, 'semantic' for root/accidental/suffix, "
            "or 'all'. Default: semantic."
        ),
    )
    parser.add_argument(
        "--measure-indices",
        help="Optional comma/range list such as '1,3,8-12'. Defaults to all measures.",
    )
    parser.add_argument(
        "--no-page-ocr",
        action="store_true",
        help="Skip page OCR and only run semantic cell crops.",
    )
    parser.add_argument(
        "--no-allowlists",
        action="store_true",
        help="Run the same semantic crops without EasyOCR allowlists.",
    )
    return parser.parse_args()


def _parse_regions(value: str) -> tuple[str, ...]:
    normalized = value.strip()
    if normalized == "semantic":
        return SEMANTIC_CHART_CELL_REGION_NAMES
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


def _count_expected_cell_calls(
    rows: list[Any],
    *,
    region_count: int,
    measure_indices: set[int] | None,
) -> int:
    count = 0
    measure_index = 1
    for row in rows:
        boundaries = getattr(row, "boundaries", [])
        for _left, _right in zip(boundaries, boundaries[1:]):
            if measure_indices is None or measure_index in measure_indices:
                count += region_count
            measure_index += 1
    return count


def _all_measure_indices(rows: list[Any]) -> set[int]:
    indices: set[int] = set()
    measure_index = 1
    for row in rows:
        boundaries = getattr(row, "boundaries", [])
        for _left, _right in zip(boundaries, boundaries[1:]):
            indices.add(measure_index)
            measure_index += 1
    return indices


def _repeat_measure_indices_from_payload(payload: dict[str, Any]) -> set[int]:
    measure_indices: set[int] = set()
    for page in payload.get("pages") or []:
        for system in page.get("systems") or []:
            for measure in system.get("measures") or []:
                if any(
                    symbol.get("type") == "repeat_previous_measure"
                    for symbol in measure.get("symbols") or []
                ):
                    measure_indices.add(int(measure.get("index")))
    return measure_indices


def _default_job_id(input_path: Path) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"chart-debug-{_safe_name(input_path.stem)}-semantic-crops-{timestamp}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "chart"


if __name__ == "__main__":
    main()
