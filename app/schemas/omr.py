from typing import Any, Literal

from pydantic import BaseModel


JobStatus = Literal["queued", "processing", "completed", "failed", "not_found"]


class OMRProcessSyncResponse(BaseModel):
    job_id: str
    status: Literal["completed"]
    musicxml_path: str
    chord_assignments_path: str
    message: str


class OMRProcessQueuedResponse(BaseModel):
    job_id: str
    status: Literal["queued"]
    message: str


class SheetMusicChordProcessResponse(BaseModel):
    job_id: str
    status: Literal["completed"]
    source_type: Literal["sheet_music"]
    chord_assignments_path: str
    chord_assignments: dict[str, Any]
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str | None = None
    musicxml_path: str | None = None
    chord_assignments_path: str | None = None
    error: str | None = None
    callback_error: str | None = None
