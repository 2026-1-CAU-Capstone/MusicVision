import json
import logging
from pathlib import Path
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from app.core.config import ALLOWED_EXTENSIONS, BASE_DIR, JOBS_DIR
from app.schemas.omr import JobStatusResponse, OMRProcessResponse
from app.services.job_service import (
    create_job_directories,
    read_job_status,
    save_upload_file,
    update_job_status,
    validate_job_id,
    write_job_status,
)
from app.services.omr_service import run_omr_pipeline


router = APIRouter()
CHORD_ASSIGNMENTS_FILENAME = "chord_assignments.json"
logger = logging.getLogger("musicvision.omr")


async def log_process_request(request: Request) -> None:
    content_type = request.headers.get("content-type")
    content_length = request.headers.get("content-length")

    try:
        form = await request.form()
        fields = [_describe_form_item(key, value) for key, value in form.multi_items()]
    except Exception:
        logger.exception(
            "Could not inspect incoming OMR request form: content_type=%r content_length=%r",
            content_type,
            content_length,
        )
        return

    logger.info(
        "Incoming OMR request: content_type=%r content_length=%r fields=%s",
        content_type,
        content_length,
        fields,
    )


def _describe_form_item(key: str, value: object) -> str:
    filename = getattr(value, "filename", None)
    content_type = getattr(value, "content_type", None)

    if filename is not None:
        return f"{key}=file(filename={filename!r}, content_type={content_type!r})"

    return f"{key}={type(value).__name__}"


@router.post(
    "/omr/process",
    response_model=OMRProcessResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(log_process_request)],
)
def process_omr(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    job_id: str | None = Form(default=None),
    callback_url: str | None = Form(default=None),
) -> OMRProcessResponse:
    requested_job_id = job_id or str(uuid4())
    safe_job_id = validate_job_id(requested_job_id)
    safe_callback_url = _validate_callback_url(callback_url)

    original_filename = file.filename or ""
    logger.info(
        "Parsed OMR upload: job_id=%s filename=%r content_type=%r callback_url=%r",
        safe_job_id,
        original_filename,
        file.content_type,
        safe_callback_url,
    )

    file_suffix = Path(original_filename).suffix.lower()
    if file_suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension. Allowed extensions: {allowed}",
        )

    job_paths = create_job_directories(safe_job_id)
    input_file_path = save_upload_file(file, job_paths.input_dir)
    logger.info(
        "Saved OMR upload: job_id=%s path=%s bytes=%s",
        safe_job_id,
        input_file_path,
        input_file_path.stat().st_size,
    )
    write_job_status(
        safe_job_id,
        status="queued",
        message="OMR processing queued",
        callback_url=safe_callback_url,
    )
    background_tasks.add_task(
        _run_omr_job,
        job_id=safe_job_id,
        input_file_path=input_file_path,
        intermediate_dir=job_paths.intermediate_dir,
        output_dir=job_paths.output_dir,
        logs_dir=job_paths.logs_dir,
        callback_url=safe_callback_url,
    )

    return OMRProcessResponse(
        job_id=safe_job_id,
        status="queued",
        message="OMR processing queued",
    )


@router.get(
    "/omr/jobs/{job_id}",
    response_model=JobStatusResponse,
    response_model_exclude_none=True,
)
def get_job_status(job_id: str) -> JobStatusResponse:
    safe_job_id = validate_job_id(job_id)
    job_status = read_job_status(safe_job_id)

    if job_status is not None:
        return _job_status_response_from_record(safe_job_id, job_status)

    job_dir = JOBS_DIR / safe_job_id
    chord_assignments_path = _find_chord_assignments_path(job_dir)

    if chord_assignments_path is not None:
        musicxml_path = job_dir / "output" / "score.musicxml"
        return JobStatusResponse(
            job_id=safe_job_id,
            status="completed",
            message="OMR processing completed",
            musicxml_path=(
                _relative_path(musicxml_path) if musicxml_path.exists() else None
            ),
            chord_assignments_path=_relative_path(chord_assignments_path),
        )

    if job_dir.exists():
        return JobStatusResponse(
            job_id=safe_job_id,
            status="processing",
            message="OMR processing in progress",
        )

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


def _find_chord_assignments_path(job_dir: Path) -> Path | None:
    canonical_path = job_dir / "output" / CHORD_ASSIGNMENTS_FILENAME
    if canonical_path.exists():
        return canonical_path

    return None


def _run_omr_job(
    *,
    job_id: str,
    input_file_path: Path,
    intermediate_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    callback_url: str | None,
) -> None:
    write_job_status(
        job_id,
        status="processing",
        message="OMR processing in progress",
        callback_url=callback_url,
    )

    try:
        pipeline_result = run_omr_pipeline(
            job_id=job_id,
            input_file_path=input_file_path,
            intermediate_dir=intermediate_dir,
            output_dir=output_dir,
            logs_dir=logs_dir,
        )
    except Exception as exc:
        logger.exception("OMR processing failed: job_id=%s", job_id)
        error_message = str(exc) or exc.__class__.__name__
        payload = write_job_status(
            job_id,
            status="failed",
            message="OMR processing failed",
            callback_url=callback_url,
            error=error_message,
        )
        _send_job_callback(job_id, callback_url, payload)
        return

    payload = write_job_status(
        job_id,
        status="completed",
        message="OMR processing completed",
        musicxml_path=_relative_path(pipeline_result.musicxml_path),
        chord_assignments_path=_relative_path(pipeline_result.chord_assignments_path),
        callback_url=callback_url,
    )
    _send_job_callback(job_id, callback_url, payload)


def _send_job_callback(
    job_id: str,
    callback_url: str | None,
    payload: dict[str, object],
) -> None:
    if callback_url is None:
        return

    callback_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"callback_url", "callback_error"}
    }
    callback_error = _post_job_callback(callback_url, callback_payload)

    if callback_error is not None:
        update_job_status(job_id, callback_error=callback_error)
        logger.warning(
            "OMR callback failed: job_id=%s callback_url=%r error=%s",
            job_id,
            callback_url,
            callback_error,
        )


def _post_job_callback(
    callback_url: str,
    payload: dict[str, object],
) -> str | None:
    request = url_request.Request(
        callback_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with url_request.urlopen(request, timeout=10) as response:
            if response.status >= 400:
                return f"callback returned HTTP {response.status}"
    except url_error.HTTPError as exc:
        return f"callback returned HTTP {exc.code}"
    except (TimeoutError, url_error.URLError) as exc:
        return str(exc)

    return None


def _validate_callback_url(callback_url: str | None) -> str | None:
    if callback_url is None or not callback_url.strip():
        return None

    trimmed_callback_url = callback_url.strip()
    parsed_url = urlparse(trimmed_callback_url)

    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="callback_url must be an absolute http(s) URL.",
        )

    return trimmed_callback_url


def _job_status_response_from_record(
    job_id: str,
    record: dict[str, object],
) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job_id,
        status=record.get("status", "processing"),
        message=record.get("message"),
        musicxml_path=record.get("musicxml_path"),
        chord_assignments_path=record.get("chord_assignments_path"),
        error=record.get("error"),
        callback_error=record.get("callback_error"),
    )


def _relative_path(path: Path) -> str:
    return path.relative_to(BASE_DIR).as_posix()
