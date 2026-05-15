from dataclasses import dataclass
from pathlib import Path

from pipeline.export import export_result_json
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
    musicxml_path = run_homr(
        preprocessed_input_path=preprocessed_input_path,
        output_dir=output_dir,
        logs_dir=logs_dir,
    )
    result_payload = postprocess_omr_output(
        job_id=job_id,
        input_file_path=input_file_path,
        musicxml_path=musicxml_path,
    )
    result_json_path = export_result_json(
        result_payload=result_payload,
        output_dir=output_dir,
    )

    return PipelineResult(
        musicxml_path=musicxml_path,
        result_json_path=result_json_path,
    )
