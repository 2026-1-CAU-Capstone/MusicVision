from pathlib import Path


def postprocess_omr_output(
    *,
    job_id: str,
    input_file_path: Path,
    musicxml_path: Path,
) -> dict[str, str]:
    """
    Build a minimal structured payload from HOMR output.

    TODO: Add semantic extraction/cleanup when richer downstream metadata is needed.
    """
    return {
        "job_id": job_id,
        "source_file": input_file_path.name,
        "musicxml_file": musicxml_path.name,
        "pipeline": "homr",
    }
