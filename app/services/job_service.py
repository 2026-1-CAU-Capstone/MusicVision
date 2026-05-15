import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import JOBS_DIR


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
