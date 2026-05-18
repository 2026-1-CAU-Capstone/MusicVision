import os
import shutil
import subprocess
import sys
from pathlib import Path

from pipeline.homr_artifacts import HomrArtifactPaths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOMR_PROJECT_DIR = PROJECT_ROOT / "homr"


def run_homr(
    *,
    preprocessed_input_path: Path,
    output_dir: Path,
    logs_dir: Path,
) -> HomrArtifactPaths:
    """
    Run the vendored HOMR CLI and return the generated output artifact paths.

    HOMR writes `<input-stem>.musicxml` next to the input image. The API exposes
    a stable `score.musicxml` filename instead, so the generated file is moved
    into the job output directory after a successful run.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    geometry_json_path = output_dir / "geometry.json"
    processed_image_path = output_dir / "homr_processed.png"
    command = [
        sys.executable,
        "-m",
        "homr.main",
        "--geometry-json",
        str(geometry_json_path.resolve()),
        "--processed-image",
        str(processed_image_path.resolve()),
        str(preprocessed_input_path.resolve()),
    ]
    homr_env = os.environ.copy()
    homr_env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        command,
        cwd=HOMR_PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
        env=homr_env,
    )

    log_path = logs_dir / "homr.log"
    log_path.write_text(
        _format_homr_log(command=command, returncode=completed.returncode, completed=completed),
        encoding="utf-8",
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"HOMR failed with exit code {completed.returncode}. See {log_path.name} for details."
        )

    generated_musicxml_path = preprocessed_input_path.with_suffix(".musicxml")
    if not generated_musicxml_path.exists():
        raise RuntimeError(
            "HOMR completed without producing a MusicXML file. "
            f"Expected {generated_musicxml_path.name}."
        )

    musicxml_path = output_dir / "score.musicxml"
    shutil.move(str(generated_musicxml_path), musicxml_path)

    if not geometry_json_path.exists():
        raise RuntimeError(
            "HOMR completed without producing geometry.json. "
            f"Expected {geometry_json_path.name}."
        )
    if not processed_image_path.exists():
        raise RuntimeError(
            "HOMR completed without producing homr_processed.png. "
            f"Expected {processed_image_path.name}."
        )

    return HomrArtifactPaths(
        musicxml_path=musicxml_path,
        geometry_json_path=geometry_json_path,
        processed_image_path=processed_image_path,
    )


def _format_homr_log(
    *,
    command: list[str],
    returncode: int,
    completed: subprocess.CompletedProcess[str],
) -> str:
    return (
        f"Command: {' '.join(command)}\n"
        f"Exit code: {returncode}\n"
        "\n"
        "[stdout]\n"
        f"{completed.stdout}"
        "\n"
        "[stderr]\n"
        f"{completed.stderr}"
    )
