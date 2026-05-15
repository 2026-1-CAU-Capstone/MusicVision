from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


class OMRProcessResponse(BaseModel):
    job_id: str
    status: Literal["completed"]
    musicxml_path: str
    result_json_path: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["completed", "processing", "not_found"]
