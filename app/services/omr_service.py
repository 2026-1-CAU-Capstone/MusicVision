from dataclasses import dataclass
from pathlib import Path

from pipeline.chords.easyocr_backend import extract_chord_tokens_ocr
from pipeline.chords.measure_assignment import assign_chords_to_measures
from pipeline.chords.ocr_common import load_rgb_image
from pipeline.chords.overlay import write_chord_assignment_overlay
from pipeline.chords.token_filters import filter_probable_non_chords, serialize_token
from pipeline.export import export_chord_assignments_json
from pipeline.homr_artifacts import load_geometry_json
from pipeline.musicxml_alignment import (
    annotate_measure_alignment,
    read_musicxml_system_measure_counts,
)
from pipeline.postprocess import postprocess_omr_output
from pipeline.preprocess import preprocess_input
from pipeline.run_homr import run_homr, run_homr_geometry_only


@dataclass(frozen=True)
class PipelineResult:
    musicxml_path: Path
    chord_assignments_path: Path


@dataclass(frozen=True)
class SheetMusicChordPipelineResult:
    chord_assignments_path: Path


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
    processed_image = load_rgb_image(homr_artifacts.processed_image_path)
    geometry = load_geometry_json(homr_artifacts.geometry_json_path)
    expected_measure_counts_by_system = read_musicxml_system_measure_counts(
        homr_artifacts.musicxml_path,
    )
    chord_tokens, ocr_rejects = extract_chord_tokens_ocr(processed_image)
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
    measure_alignment = annotate_measure_alignment(
        chord_result=chord_result,
        musicxml_path=homr_artifacts.musicxml_path,
    )
    ocr_diagnostics = {
        "backend": "easyocr",
        "accepted_tokens": [serialize_token(token) for token in chord_tokens],
        "rejected_hits": ocr_rejects,
        "filtered_hits": filtered_hits,
    }
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
    chord_tokens, ocr_rejects = extract_chord_tokens_ocr(processed_image)
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
        "backend": "easyocr",
        "accepted_tokens": [serialize_token(token) for token in chord_tokens],
        "rejected_hits": ocr_rejects,
        "filtered_hits": filtered_hits,
    }
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
