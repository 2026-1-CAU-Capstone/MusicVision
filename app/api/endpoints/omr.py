from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.core.config import ALLOWED_EXTENSIONS, BASE_DIR, JOBS_DIR
from app.schemas.omr import JobStatusResponse, OMRProcessResponse
from app.services.job_service import (
    create_job_directories,
    save_upload_file,
    validate_job_id,
)
from app.services.omr_service import run_omr_pipeline


router = APIRouter()
CHORD_ASSIGNMENTS_FILENAME = "chord_assignments.json"
LEGACY_RESULT_FILENAME = "result.json"


@router.post("/omr/process", response_model=OMRProcessResponse)
def process_omr(
    file: UploadFile = File(...),
    job_id: str | None = Form(default=None),
) -> OMRProcessResponse:
    requested_job_id = job_id or str(uuid4())
    safe_job_id = validate_job_id(requested_job_id)

    original_filename = file.filename or ""
    file_suffix = Path(original_filename).suffix.lower()
    if file_suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension. Allowed extensions: {allowed}",
        )

    job_paths = create_job_directories(safe_job_id)
    input_file_path = save_upload_file(file, job_paths.input_dir)
    pipeline_result = run_omr_pipeline(
        job_id=safe_job_id,
        input_file_path=input_file_path,
        intermediate_dir=job_paths.intermediate_dir,
        output_dir=job_paths.output_dir,
        logs_dir=job_paths.logs_dir,
    )

    return OMRProcessResponse(
        job_id=safe_job_id,
        status="completed",
        musicxml_path=pipeline_result.musicxml_path.relative_to(BASE_DIR).as_posix(),
        chord_assignments_path=(
            pipeline_result.chord_assignments_path.relative_to(BASE_DIR).as_posix()
        ),
        message="OMR processing completed",
    )


@router.get("/omr/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    safe_job_id = validate_job_id(job_id)
    job_dir = JOBS_DIR / safe_job_id
    chord_assignments_path = _find_chord_assignments_path(job_dir)

    if chord_assignments_path is not None:
        return JobStatusResponse(job_id=safe_job_id, status="completed")

    if job_dir.exists():
        return JobStatusResponse(job_id=safe_job_id, status="processing")

    return JobStatusResponse(job_id=safe_job_id, status="not_found")


@router.get("/omr/jobs/{job_id}/musicxml", response_class=FileResponse)
def get_job_musicxml(job_id: str) -> FileResponse:
    """
    Return the generated MusicXML file for a completed OMR job.

    This is intended for service-to-service retrieval, such as a Spring Boot
    backend fetching the OMR result before forwarding or storing it.
    """
    safe_job_id = validate_job_id(job_id)
    musicxml_path = JOBS_DIR / safe_job_id / "output" / "score.musicxml"

    if not musicxml_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MusicXML result not found",
        )

    return FileResponse(
        path=musicxml_path,
        media_type="application/vnd.recordare.musicxml+xml",
        filename="score.musicxml",
    )


@router.get("/omr/jobs/{job_id}/chord-assignments", response_class=FileResponse)
def get_job_chord_assignments(job_id: str) -> FileResponse:
    safe_job_id = validate_job_id(job_id)
    chord_assignments_path = _find_chord_assignments_path(JOBS_DIR / safe_job_id)

    if chord_assignments_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chord assignments not found",
        )

    return FileResponse(
        path=chord_assignments_path,
        media_type="application/json",
        filename=CHORD_ASSIGNMENTS_FILENAME,
    )


@router.get("/omr/jobs/{job_id}/result", response_class=FileResponse)
def get_job_result(job_id: str) -> FileResponse:
    """
    Backward-compatible alias for the former generic structured-result route.

    New callers should prefer `/chord-assignments`.
    """
    safe_job_id = validate_job_id(job_id)
    chord_assignments_path = _find_chord_assignments_path(JOBS_DIR / safe_job_id)

    if chord_assignments_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Structured result not found",
        )

    return FileResponse(
        path=chord_assignments_path,
        media_type="application/json",
        filename=CHORD_ASSIGNMENTS_FILENAME,
    )


def _find_chord_assignments_path(job_dir: Path) -> Path | None:
    output_dir = job_dir / "output"
    canonical_path = output_dir / CHORD_ASSIGNMENTS_FILENAME
    if canonical_path.exists():
        return canonical_path

    legacy_path = output_dir / LEGACY_RESULT_FILENAME
    if legacy_path.exists():
        return legacy_path

    return None
