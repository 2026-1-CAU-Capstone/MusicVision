import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.core.config import JOBS_DIR


JOB_STATUS_FILENAME = "job_status.json"
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class JobPaths:
    job_dir: Path
    input_dir: Path
    intermediate_dir: Path
    output_dir: Path
    logs_dir: Path


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="job_id may only contain letters, numbers, underscores, and hyphens.",
        )
    return job_id


def create_job_directories(job_id: str) -> JobPaths:
    job_dir = JOBS_DIR / job_id
    input_dir = job_dir / "input"
    intermediate_dir = job_dir / "intermediate"
    output_dir = job_dir / "output"
    logs_dir = job_dir / "logs"

    for directory in (input_dir, intermediate_dir, output_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    return JobPaths(
        job_dir=job_dir,
        input_dir=input_dir,
        intermediate_dir=intermediate_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
    )


def read_job_status(job_id: str) -> dict[str, Any] | None:
    status_path = JOBS_DIR / job_id / JOB_STATUS_FILENAME

    if not status_path.exists():
        return None

    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_job_status(
    job_id: str,
    *,
    status: str,
    message: str,
    musicxml_path: str | None = None,
    chord_assignments_path: str | None = None,
    chord_chart_path: str | None = None,
    callback_url: str | None = None,
    error: str | None = None,
    callback_error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "message": message,
    }
    optional_fields = {
        "musicxml_path": musicxml_path,
        "chord_assignments_path": chord_assignments_path,
        "chord_chart_path": chord_chart_path,
        "callback_url": callback_url,
        "error": error,
        "callback_error": callback_error,
    }
    payload.update(
        {
            key: value
            for key, value in optional_fields.items()
            if value is not None
        }
    )

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    status_path = job_dir / JOB_STATUS_FILENAME
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return payload


def update_job_status(job_id: str, **updates: Any) -> dict[str, Any]:
    current_status = read_job_status(job_id) or {"job_id": job_id}
    current_status.update(
        {key: value for key, value in updates.items() if value is not None}
    )

    return write_job_status(
        job_id,
        status=current_status["status"],
        message=current_status["message"],
        musicxml_path=current_status.get("musicxml_path"),
        chord_assignments_path=current_status.get("chord_assignments_path"),
        chord_chart_path=current_status.get("chord_chart_path"),
        callback_url=current_status.get("callback_url"),
        error=current_status.get("error"),
        callback_error=current_status.get("callback_error"),
    )


def save_upload_file(file: UploadFile, input_dir: Path) -> Path:
    safe_filename = sanitize_filename(file.filename or "upload")
    destination = input_dir / safe_filename

    with destination.open("wb") as output_file:
        shutil.copyfileobj(file.file, output_file)

    return destination


def sanitize_filename(filename: str) -> str:
    basename = Path(filename).name
    sanitized = SAFE_FILENAME_PATTERN.sub("_", basename).strip("._")

    if not sanitized:
        sanitized = "upload"

    suffix = Path(basename).suffix.lower()
    if suffix and not sanitized.lower().endswith(suffix):
        sanitized = f"{sanitized}{suffix}"

    return sanitized
