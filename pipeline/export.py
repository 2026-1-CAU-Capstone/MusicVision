import json
from pathlib import Path


def export_result_json(*, result_payload: dict[str, str], output_dir: Path) -> Path:
    """
    Write the pipeline result payload to result.json.

    TODO: Extend the exported schema when real OMR metadata becomes available.
    """
    result_json_path = output_dir / "result.json"
    result_json_path.write_text(
        json.dumps(result_payload, indent=2),
        encoding="utf-8",
    )
    return result_json_path
