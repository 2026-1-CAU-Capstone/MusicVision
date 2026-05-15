from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.api.endpoints.omr as omr_endpoint
import app.services.job_service as job_service


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    jobs_dir = tmp_path / "jobs"

    monkeypatch.setattr(omr_endpoint, "BASE_DIR", tmp_path)
    monkeypatch.setattr(omr_endpoint, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(job_service, "JOBS_DIR", jobs_dir)

    with TestClient(app) as test_client:
        yield test_client
