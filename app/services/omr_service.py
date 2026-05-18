from dataclasses import dataclass
from pathlib import Path

from pipeline.chords.easyocr_backend import extract_chord_tokens_ocr
from pipeline.chords.measure_assignment import assign_chords_to_measures
from pipeline.chords.ocr_common import load_rgb_image
from pipeline.export import export_result_json
from pipeline.homr_artifacts import load_geometry_json
from pipeline.postprocess import postprocess_omr_output
from pipeline.preprocess import preprocess_input
from pipeline.run_homr import run_homr


@dataclass(frozen=True)
class PipelineResult:
    musicxml_path: Path
    result_json_path: Path


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
    chord_tokens, _ocr_rejects = extract_chord_tokens_ocr(processed_image)
    chord_result = assign_chords_to_measures(
        tokens=chord_tokens,
        geometry=geometry,
        image=processed_image,
        source_path=homr_artifacts.processed_image_path.name,
    )
    result_payload = postprocess_omr_output(
        job_id=job_id,
        input_file_path=input_file_path,
        homr_artifacts=homr_artifacts,
        chord_result=chord_result,
    )
    result_json_path = export_result_json(
        result_payload=result_payload,
        output_dir=output_dir,
    )

    return PipelineResult(
        musicxml_path=homr_artifacts.musicxml_path,
        result_json_path=result_json_path,
    )
