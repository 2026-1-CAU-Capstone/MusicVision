import json
from pathlib import Path
from typing import Any


CHORD_ASSIGNMENTS_FILENAME = "chord_assignments.json"
CHORD_CHART_FILENAME = "chord_chart.json"
CHORD_CHART_DEBUG_FILENAME = "chord_chart_debug.json"


def export_chord_assignments_json(
    *,
    result_payload: dict[str, Any],
    output_dir: Path,
) -> Path:
    """
    Write the structured printed-chord assignment payload to disk.

    TODO: Extend the exported schema when real OMR metadata becomes available.
    """
    chord_assignments_path = output_dir / CHORD_ASSIGNMENTS_FILENAME
    chord_assignments_path.write_text(
        json.dumps(result_payload, indent=2),
        encoding="utf-8",
    )
    return chord_assignments_path


def export_chord_chart_json(
    *,
    result_payload: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write the structured chord-chart payload to disk."""
    chord_chart_path = output_dir / CHORD_CHART_FILENAME
    chord_chart_path.write_text(
        json.dumps(result_payload, indent=2),
        encoding="utf-8",
    )
    return chord_chart_path


def export_chord_chart_debug_json(
    *,
    result_payload: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write the full diagnostic chord-chart payload to disk."""
    chord_chart_debug_path = output_dir / CHORD_CHART_DEBUG_FILENAME
    chord_chart_debug_path.write_text(
        json.dumps(result_payload, indent=2),
        encoding="utf-8",
    )
    return chord_chart_debug_path
