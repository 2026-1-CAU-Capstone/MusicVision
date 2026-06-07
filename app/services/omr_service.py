from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.chord_charts.ocr_backend import (
    CHART_SEMANTIC_REGION_ALLOWLISTS,
    MULTI_CHORD_CHART_CELL_REGION_NAMES,
    SEMANTIC_CHART_CELL_REGION_NAMES,
    build_root_anchor_candidates,
    chart_cell_ocr_region_boxes,
    chart_row_ocr_region_boxes,
    chart_root_anchor_local_region_boxes,
    extract_chart_cell_ocr_tokens,
    extract_chart_ocr_tokens,
    extract_chart_root_anchor_local_ocr_tokens,
    extract_chart_row_ocr_tokens,
)
from pipeline.chord_charts.image_preprocessing import upscale_small_chord_chart_image
from pipeline.chord_charts.overlay import (
    write_chord_chart_ocr_debug_overlay,
    write_chord_chart_overlay,
)
from pipeline.chord_charts.ocr_strategy import (
    plan_multi_chord_chart_cell_ocr,
    plan_selective_chart_cell_ocr,
    root_anchor_hints_from_plan,
)
from pipeline.chord_charts.parser import detect_chart_grid, parse_chord_chart_image
from pipeline.chord_charts.public_payload import build_public_chord_chart_payload
from pipeline.chord_charts.semantic_assembly import assemble_semantic_chord_tokens
from pipeline.chords.easyocr_backend import extract_chord_tokens_ocr
from pipeline.chords.measure_assignment import assign_chords_to_measures
from pipeline.chords.ocr_common import load_rgb_image
from pipeline.chords.overlay import write_chord_assignment_overlay
from pipeline.chords.paddleocr_rescue import maybe_apply_paddleocr_rescue
from pipeline.chords.token_filters import filter_probable_non_chords, serialize_token
from pipeline.export import (
    export_chord_assignments_json,
    export_chord_chart_debug_json,
    export_chord_chart_json,
)
from pipeline.homr_artifacts import load_geometry_json
from pipeline.musicxml_alignment import (
    annotate_measure_alignment,
    read_musicxml_system_measure_counts,
)
from pipeline.postprocess import postprocess_omr_output
from pipeline.preprocess import preprocess_input
from pipeline.run_homr import run_homr, run_homr_geometry_only
from pipeline.sheet_music_structure import (
    annotate_ending_markers,
    apply_ending_markers_to_musicxml,
    clean_single_staff_redundant_clefs,
    detect_ending_markers,
)


ProgressCallback = Callable[
    [int, str, str | None, int | None, int | None],
    None,
]


@dataclass(frozen=True)
class PipelineResult:
    musicxml_path: Path
    chord_assignments_path: Path


@dataclass(frozen=True)
class SheetMusicChordPipelineResult:
    chord_assignments_path: Path


@dataclass(frozen=True)
class ChordChartPipelineResult:
    chord_chart_path: Path
    chord_chart_debug_path: Path | None = None


def run_omr_pipeline(
    *,
    job_id: str,
    input_file_path: Path,
    intermediate_dir: Path,
    output_dir: Path,
    logs_dir: Path,
) -> PipelineResult:
    preprocessed_input_path = preprocess_input(
        input_file_path=input_file_path,
        intermediate_dir=intermediate_dir,
    )
    homr_artifacts = run_homr(
        preprocessed_input_path=preprocessed_input_path,
        output_dir=output_dir,
        logs_dir=logs_dir,
    )
    musicxml_postprocess = clean_single_staff_redundant_clefs(
        homr_artifacts.musicxml_path,
    )
    processed_image = load_rgb_image(homr_artifacts.processed_image_path)
    geometry = load_geometry_json(homr_artifacts.geometry_json_path)
    expected_measure_counts_by_system = read_musicxml_system_measure_counts(
        homr_artifacts.musicxml_path,
    )
    chord_tokens, ocr_rejects, ocr_strategy = extract_chord_tokens_ocr(
        processed_image,
        geometry=geometry,
        return_strategy=True,
    )
    chord_tokens, ocr_rejects, paddleocr_rescue = maybe_apply_paddleocr_rescue(
        processed_image_path=homr_artifacts.processed_image_path,
        geometry=geometry,
        tokens=chord_tokens,
        rejects=ocr_rejects,
        output_dir=output_dir,
    )
    chord_tokens, filtered_hits = filter_probable_non_chords(
        tokens=chord_tokens,
        image=processed_image,
        geometry=geometry,
    )
    chord_result = assign_chords_to_measures(
        tokens=chord_tokens,
        geometry=geometry,
        image=processed_image,
        source_path=homr_artifacts.processed_image_path.name,
        expected_measure_counts_by_system=expected_measure_counts_by_system,
    )
    ending_markers = detect_ending_markers(
        image=processed_image,
        pages=chord_result["pages"],
    )
    annotate_ending_markers(
        pages=chord_result["pages"],
        markers=ending_markers,
    )
    measure_alignment = annotate_measure_alignment(
        chord_result=chord_result,
        musicxml_path=homr_artifacts.musicxml_path,
    )
    musicxml_postprocess["detected_endings"] = [
        marker.to_dict() for marker in ending_markers
    ]
    musicxml_postprocess.update(
        apply_ending_markers_to_musicxml(
            musicxml_path=homr_artifacts.musicxml_path,
            pages=chord_result["pages"],
            markers=ending_markers,
        )
    )
    ocr_diagnostics = {
        "backend": "easyocr+paddleocr_rescue"
        if paddleocr_rescue and paddleocr_rescue.get("enabled")
        else "easyocr",
        "strategy": ocr_strategy,
        "accepted_tokens": [serialize_token(token) for token in chord_tokens],
        "rejected_hits": ocr_rejects,
        "filtered_hits": filtered_hits,
    }
    if paddleocr_rescue is not None:
        ocr_diagnostics["paddleocr_rescue"] = paddleocr_rescue
    overlay_path = write_chord_assignment_overlay(
        image=processed_image,
        pages=chord_result["pages"],
        ocr_diagnostics=ocr_diagnostics,
        output_dir=output_dir,
    )
    result_payload = postprocess_omr_output(
        job_id=job_id,
        input_file_path=input_file_path,
        homr_artifacts=homr_artifacts,
        chord_result=chord_result,
        ocr_diagnostics=ocr_diagnostics,
        overlay_path=overlay_path,
        measure_alignment=measure_alignment,
    )
    result_payload["musicxml_postprocess"] = musicxml_postprocess
    chord_assignments_path = export_chord_assignments_json(
        result_payload=result_payload,
        output_dir=output_dir,
    )

    return PipelineResult(
        musicxml_path=homr_artifacts.musicxml_path,
        chord_assignments_path=chord_assignments_path,
    )


def run_sheet_music_chord_pipeline(
    *,
    job_id: str,
    input_file_path: Path,
    intermediate_dir: Path,
    output_dir: Path,
    logs_dir: Path,
) -> SheetMusicChordPipelineResult:
    preprocessed_input_path = preprocess_input(
        input_file_path=input_file_path,
        intermediate_dir=intermediate_dir,
    )
    homr_artifacts = run_homr_geometry_only(
        preprocessed_input_path=preprocessed_input_path,
        output_dir=output_dir,
        logs_dir=logs_dir,
    )
    processed_image = load_rgb_image(homr_artifacts.processed_image_path)
    geometry = load_geometry_json(homr_artifacts.geometry_json_path)
    chord_tokens, ocr_rejects, ocr_strategy = extract_chord_tokens_ocr(
        processed_image,
        geometry=geometry,
        return_strategy=True,
    )
    chord_tokens, ocr_rejects, paddleocr_rescue = maybe_apply_paddleocr_rescue(
        processed_image_path=homr_artifacts.processed_image_path,
        geometry=geometry,
        tokens=chord_tokens,
        rejects=ocr_rejects,
        output_dir=output_dir,
    )
    chord_tokens, filtered_hits = filter_probable_non_chords(
        tokens=chord_tokens,
        image=processed_image,
        geometry=geometry,
    )
    chord_result = assign_chords_to_measures(
        tokens=chord_tokens,
        geometry=geometry,
        image=processed_image,
        source_path=homr_artifacts.processed_image_path.name,
    )
    ocr_diagnostics = {
        "backend": "easyocr+paddleocr_rescue"
        if paddleocr_rescue and paddleocr_rescue.get("enabled")
        else "easyocr",
        "strategy": ocr_strategy,
        "accepted_tokens": [serialize_token(token) for token in chord_tokens],
        "rejected_hits": ocr_rejects,
        "filtered_hits": filtered_hits,
    }
    if paddleocr_rescue is not None:
        ocr_diagnostics["paddleocr_rescue"] = paddleocr_rescue
    overlay_path = write_chord_assignment_overlay(
        image=processed_image,
        pages=chord_result["pages"],
        ocr_diagnostics=ocr_diagnostics,
        output_dir=output_dir,
    )
    result_payload = _postprocess_sheet_music_chord_output(
        job_id=job_id,
        input_file_path=input_file_path,
        geometry_json_path=homr_artifacts.geometry_json_path,
        processed_image_path=homr_artifacts.processed_image_path,
        chord_result=chord_result,
        ocr_diagnostics=ocr_diagnostics,
        overlay_path=overlay_path,
    )
    chord_assignments_path = export_chord_assignments_json(
        result_payload=result_payload,
        output_dir=output_dir,
    )

    return SheetMusicChordPipelineResult(chord_assignments_path=chord_assignments_path)


def run_chord_chart_pipeline(
    *,
    job_id: str,
    input_file_path: Path,
    intermediate_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> ChordChartPipelineResult:
    del logs_dir

    _report_progress(
        progress_callback,
        progress=8,
        stage="preprocessing",
        message="Preprocessing chord chart image",
    )
    preprocessed_input_path = preprocess_input(
        input_file_path=input_file_path,
        intermediate_dir=intermediate_dir,
    )
    _report_progress(
        progress_callback,
        progress=12,
        stage="loading_image",
        message="Loading preprocessed chord chart image",
    )
    image = load_rgb_image(preprocessed_input_path)
    image_scale = upscale_small_chord_chart_image(image)
    image = image_scale.image
    _report_progress(
        progress_callback,
        progress=20,
        stage="detecting_grid",
        message="Detecting chord chart grid",
    )
    rows = detect_chart_grid(image)
    _report_progress(
        progress_callback,
        progress=32,
        stage="page_ocr",
        message="Reading chart page text",
    )
    page_tokens, page_rejects = extract_chart_ocr_tokens(image)
    _report_progress(
        progress_callback,
        progress=42,
        stage="row_ocr",
        message="Reading chart rows",
        current_step=0,
        total_steps=len(rows),
    )
    row_tokens, row_rejects = extract_chart_row_ocr_tokens(
        image,
        rows,
        progress_callback=_chart_ocr_progress_callback(
            progress_callback,
            start_progress=42,
            progress_span=18,
            stage="row_ocr",
            message_prefix="Reading chart rows",
        ),
    )
    selective_plan = plan_selective_chart_cell_ocr(
        rows=rows,
        page_tokens=page_tokens,
        row_tokens=row_tokens,
    )
    multi_chord_plan = plan_multi_chord_chart_cell_ocr(
        rows=rows,
        page_tokens=page_tokens,
        row_tokens=row_tokens,
    )
    selective_region_names = SEMANTIC_CHART_CELL_REGION_NAMES
    selective_steps = len(selective_plan.measure_indices) * len(selective_region_names)
    root_anchor_probe_steps = (
        len(multi_chord_plan.measure_indices) * len(MULTI_CHORD_CHART_CELL_REGION_NAMES)
    )
    _report_progress(
        progress_callback,
        progress=60,
        stage="selective_cell_ocr",
        message="Reading suspicious chart cells",
        current_step=0,
        total_steps=selective_steps,
    )
    cell_tokens, cell_rejects = extract_chart_cell_ocr_tokens(
        image,
        rows,
        measure_indices=set(selective_plan.measure_indices),
        region_names=selective_region_names,
        region_allowlists=CHART_SEMANTIC_REGION_ALLOWLISTS,
        source="cell_ocr_targeted",
        progress_callback=_chart_ocr_progress_callback(
            progress_callback,
            start_progress=60,
            progress_span=20,
            stage="selective_cell_ocr",
            message_prefix="Reading suspicious chart cells",
        ),
    )
    core_cell_token_count = len(cell_tokens)
    core_cell_reject_count = len(cell_rejects)
    root_anchor_probe_tokens = []
    root_anchor_probe_rejects = []
    root_anchor_candidates = []
    root_anchor_local_tokens = []
    root_anchor_local_rejects = []
    root_anchor_local_steps = 0
    if multi_chord_plan.measure_indices:
        root_anchor_hints = root_anchor_hints_from_plan(multi_chord_plan)
        root_anchor_probe_tokens, root_anchor_probe_rejects = extract_chart_cell_ocr_tokens(
            image,
            rows,
            measure_indices=set(multi_chord_plan.measure_indices),
            region_names=MULTI_CHORD_CHART_CELL_REGION_NAMES,
            region_allowlists=CHART_SEMANTIC_REGION_ALLOWLISTS,
            source="cell_ocr_root_anchor_probe",
            progress_callback=_chart_ocr_progress_callback(
                progress_callback,
                start_progress=60,
                progress_span=20,
                stage="selective_cell_ocr",
                message_prefix="Reading multi-chord root anchors",
            ),
        )
        cell_rejects.extend(root_anchor_probe_rejects)
        root_anchor_candidates = build_root_anchor_candidates(
            root_anchor_probe_tokens,
            image=image,
            rows=rows,
            measure_indices=set(multi_chord_plan.measure_indices),
            anchor_hints=root_anchor_hints,
        )
        root_anchor_local_steps = len(
            chart_root_anchor_local_region_boxes(
                image,
                rows,
                anchor_candidates=root_anchor_candidates,
                measure_indices=set(multi_chord_plan.measure_indices),
                source="cell_ocr_root_anchor",
            )
        )
        if root_anchor_local_steps:
            root_anchor_local_tokens, root_anchor_local_rejects = (
                extract_chart_root_anchor_local_ocr_tokens(
                    image,
                    rows,
                    anchor_candidates=root_anchor_candidates,
                    measure_indices=set(multi_chord_plan.measure_indices),
                    region_allowlists=CHART_SEMANTIC_REGION_ALLOWLISTS,
                    source="cell_ocr_root_anchor",
                    progress_callback=_chart_ocr_progress_callback(
                        progress_callback,
                        start_progress=60,
                        progress_span=20,
                        stage="selective_cell_ocr",
                        message_prefix="Reading root-anchor chart cells",
                    ),
                )
            )
            cell_tokens.extend(root_anchor_local_tokens)
            cell_rejects.extend(root_anchor_local_rejects)
    semantic_assembly = assemble_semantic_chord_tokens(
        cell_tokens,
        image=image,
    )
    _report_progress(
        progress_callback,
        progress=82,
        stage="parsing",
        message="Parsing chord chart symbols",
    )
    result_payload = parse_chord_chart_image(
        image=image,
        tokens=[*page_tokens, *row_tokens, *semantic_assembly.tokens],
        ocr_rejects=[*page_rejects, *row_rejects, *cell_rejects],
        job_id=job_id,
        source_file=input_file_path.name,
        rows=rows,
    )
    result_payload["chart_ocr"]["strategy"] = {
        **selective_plan.diagnostics,
        "page_tokens": len(page_tokens),
        "page_rejects": len(page_rejects),
        "row_tokens": len(row_tokens),
        "row_rejects": len(row_rejects),
        "targeted_cell_tokens": core_cell_token_count,
        "targeted_cell_rejects": core_cell_reject_count,
        "total_cell_tokens": len(cell_tokens),
        "total_cell_rejects": len(cell_rejects),
        "targeted_semantic_assembled_tokens": len(semantic_assembly.tokens),
        "targeted_cell_region_names": list(selective_region_names),
        "targeted_cell_ocr_calls": selective_steps,
        "multi_chord_supplemental_region_names": list(
            MULTI_CHORD_CHART_CELL_REGION_NAMES
        ),
        "multi_chord_supplemental_measure_indices": multi_chord_plan.measure_indices,
        "multi_chord_supplemental_ocr_calls": root_anchor_probe_steps,
        "multi_chord_supplemental_tokens": len(root_anchor_local_tokens),
        "multi_chord_supplemental_rejects": (
            len(root_anchor_probe_rejects) + len(root_anchor_local_rejects)
        ),
        "multi_chord_anchor_probe_tokens": len(root_anchor_probe_tokens),
        "multi_chord_anchor_probe_rejects": len(root_anchor_probe_rejects),
        "multi_chord_anchor_candidates": [
            anchor.to_dict() for anchor in root_anchor_candidates
        ],
        "multi_chord_anchor_local_ocr_calls": root_anchor_local_steps,
        "multi_chord_anchor_local_tokens": len(root_anchor_local_tokens),
        "multi_chord_anchor_local_rejects": len(root_anchor_local_rejects),
        "multi_chord_supplemental_plan": multi_chord_plan.diagnostics,
        "region_allowlists_enabled": True,
        "semantic_assembly": semantic_assembly.diagnostics,
        "image_scaling": image_scale.to_dict(),
    }
    scan_regions = [
        {
            "source": "page_ocr",
            "region": "page",
            "bbox": [0.0, 0.0, float(image.shape[1]), float(image.shape[0])],
        },
        *chart_row_ocr_region_boxes(image, rows),
        *chart_cell_ocr_region_boxes(
            image,
            rows,
            measure_indices=set(selective_plan.measure_indices),
            region_names=selective_region_names,
            source="cell_ocr_targeted",
        ),
        *chart_cell_ocr_region_boxes(
            image,
            rows,
            measure_indices=set(multi_chord_plan.measure_indices),
            region_names=MULTI_CHORD_CHART_CELL_REGION_NAMES,
            source="cell_ocr_root_anchor_probe",
        ),
        *chart_root_anchor_local_region_boxes(
            image,
            rows,
            anchor_candidates=root_anchor_candidates,
            measure_indices=set(multi_chord_plan.measure_indices),
            source="cell_ocr_root_anchor",
        ),
    ]
    _report_progress(
        progress_callback,
        progress=92,
        stage="overlay",
        message="Writing chord chart overlay",
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
            *row_tokens,
            *root_anchor_probe_tokens,
            *cell_tokens,
            *semantic_assembly.tokens,
        ],
        ocr_rejects=[*page_rejects, *row_rejects, *cell_rejects],
        scan_regions=scan_regions,
        output_dir=output_dir,
    )
    result_payload["overlay_file"] = overlay_path.name
    result_payload["debug_overlay_file"] = debug_overlay_path.name
    result_payload["chart_ocr"]["debug_overlay_file"] = debug_overlay_path.name
    _report_progress(
        progress_callback,
        progress=97,
        stage="exporting",
        message="Writing chord chart output",
    )
    chord_chart_debug_path = export_chord_chart_debug_json(
        result_payload=result_payload,
        output_dir=output_dir,
    )
    chord_chart_path = export_chord_chart_json(
        result_payload=build_public_chord_chart_payload(result_payload),
        output_dir=output_dir,
    )

    return ChordChartPipelineResult(
        chord_chart_path=chord_chart_path,
        chord_chart_debug_path=chord_chart_debug_path,
    )


def _report_progress(
    progress_callback: ProgressCallback | None,
    *,
    progress: int,
    stage: str,
    message: str | None,
    current_step: int | None = None,
    total_steps: int | None = None,
) -> None:
    if progress_callback is None:
        return

    progress_callback(progress, stage, message, current_step, total_steps)


def _chart_ocr_progress_callback(
    progress_callback: ProgressCallback | None,
    *,
    start_progress: int,
    progress_span: int,
    stage: str,
    message_prefix: str,
) -> Callable[[int, int], None] | None:
    if progress_callback is None:
        return None

    def report_ocr_progress(completed_steps: int, total_steps: int) -> None:
        progress = start_progress
        if total_steps > 0:
            progress = start_progress + int(
                (completed_steps / total_steps) * progress_span
            )
        _report_progress(
            progress_callback,
            progress=min(80, progress),
            stage=stage,
            message=f"{message_prefix} ({completed_steps}/{total_steps})",
            current_step=completed_steps,
            total_steps=total_steps,
        )

    return report_ocr_progress


def _postprocess_sheet_music_chord_output(
    *,
    job_id: str,
    input_file_path: Path,
    geometry_json_path: Path,
    processed_image_path: Path,
    chord_result: dict,
    ocr_diagnostics: dict,
    overlay_path: Path,
) -> dict:
    return {
        "job_id": job_id,
        "source_file": input_file_path.name,
        "source_type": "sheet_music",
        "geometry_file": geometry_json_path.name,
        "processed_image_file": processed_image_path.name,
        "overlay_file": overlay_path.name,
        "pipeline": "homr_geometry_only",
        "time_signature": chord_result["time_signature"],
        "beats_per_bar": chord_result["beats_per_bar"],
        "measure_alignment": _visual_only_measure_alignment(chord_result),
        "chord_ocr": ocr_diagnostics,
        "pages": chord_result["pages"],
    }


def _visual_only_measure_alignment(chord_result: dict) -> dict:
    visual_system_count = sum(len(page.get("systems") or []) for page in chord_result["pages"])
    visual_measure_count = sum(
        len(system.get("measures") or [])
        for page in chord_result["pages"]
        for system in page.get("systems") or []
    )
    return {
        "status": "visual_only",
        "musicxml_measure_count": None,
        "visual_measure_count": visual_measure_count,
        "musicxml_system_count": None,
        "visual_system_count": visual_system_count,
        "aligned_system_count": 0,
        "mismatched_system_count": 0,
        "system_alignment": [],
    }
