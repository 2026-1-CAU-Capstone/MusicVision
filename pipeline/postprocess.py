from pathlib import Path
from typing import Any

from pipeline.homr_artifacts import HomrArtifactPaths

def postprocess_omr_output(
    *,
    job_id: str,
    input_file_path: Path,
    homr_artifacts: HomrArtifactPaths,
    chord_result: dict[str, Any],
    ocr_diagnostics: dict[str, Any],
    overlay_path: Path,
    measure_alignment: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a minimal structured payload from HOMR output.

    TODO: Add semantic extraction/cleanup when richer downstream metadata is needed.
    """
    return {
        "job_id": job_id,
        "source_file": input_file_path.name,
        "musicxml_file": homr_artifacts.musicxml_path.name,
        "geometry_file": homr_artifacts.geometry_json_path.name,
        "processed_image_file": homr_artifacts.processed_image_path.name,
        "overlay_file": overlay_path.name,
        "pipeline": "homr",
        "time_signature": chord_result["time_signature"],
        "beats_per_bar": chord_result["beats_per_bar"],
        "measure_alignment": measure_alignment,
        "chord_ocr": ocr_diagnostics,
        "pages": chord_result["pages"],
    }
