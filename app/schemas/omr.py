from typing import Literal

from pydantic import BaseModel


JobStatus = Literal["queued", "processing", "completed", "failed", "not_found"]


class OMRProcessResponse(BaseModel):
    job_id: str
    status: Literal["queued"]
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str | None = None
    musicxml_path: str | None = None
    chord_assignments_path: str | None = None
    error: str | None = None
    callback_error: str | None = None
