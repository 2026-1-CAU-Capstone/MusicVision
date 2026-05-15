from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.config import ALLOWED_EXTENSIONS, BASE_DIR, JOBS_DIR
from app.schemas.omr import JobStatusResponse, OMRProcessResponse
from app.services.job_service import (
    create_job_directories,
    save_upload_file,
    validate_job_id,
)
from app.services.omr_service import run_omr_pipeline


router = APIRouter()


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
        result_json_path=pipeline_result.result_json_path.relative_to(BASE_DIR).as_posix(),
        message="OMR processing completed",
    )


@router.get("/omr/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    safe_job_id = validate_job_id(job_id)
    job_dir = JOBS_DIR / safe_job_id
    result_json_path = job_dir / "output" / "result.json"

    if result_json_path.exists():
        return JobStatusResponse(job_id=safe_job_id, status="completed")

    if job_dir.exists():
        return JobStatusResponse(job_id=safe_job_id, status="processing")

    return JobStatusResponse(job_id=safe_job_id, status="not_found")
