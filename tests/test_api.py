from io import BytesIO
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

import pipeline.run_homr as run_homr_module


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_omr_creates_outputs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_homr_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        input_path = Path(command[-1])
        input_path.with_suffix(".musicxml").write_text("<score-partwise/>", encoding="utf-8")
        assert env["PYTHONUTF8"] == "1"
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="Finished parsing 1 staves\n",
        )

    monkeypatch.setattr(run_homr_module.subprocess, "run", fake_homr_run)

    response = client.post(
        "/omr/process",
        data={"job_id": "demo-job"},
        files={"file": ("../../score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "demo-job",
        "status": "completed",
        "musicxml_path": "jobs/demo-job/output/score.musicxml",
        "result_json_path": "jobs/demo-job/output/result.json",
        "message": "OMR processing completed",
    }

    completed = client.get("/omr/jobs/demo-job")
    assert completed.status_code == 200
    assert completed.json() == {"job_id": "demo-job", "status": "completed"}


def test_process_omr_rejects_unsupported_extensions(client: TestClient) -> None:
    response = client.post(
        "/omr/process",
        files={"file": ("score.txt", BytesIO(b"not-supported"), "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png"
    }


def test_job_status_reports_processing_and_missing(client: TestClient, tmp_path) -> None:
    processing_job_dir = tmp_path / "jobs" / "pending-job"
    processing_job_dir.mkdir(parents=True)

    processing = client.get("/omr/jobs/pending-job")
    missing = client.get("/omr/jobs/missing-job")

    assert processing.status_code == 200
    assert processing.json() == {"job_id": "pending-job", "status": "processing"}
    assert missing.status_code == 200
    assert missing.json() == {"job_id": "missing-job", "status": "not_found"}


def test_get_job_musicxml_returns_file(client: TestClient, tmp_path: Path) -> None:
    musicxml_path = tmp_path / "jobs" / "ready-job" / "output" / "score.musicxml"
    musicxml_path.parent.mkdir(parents=True)
    musicxml_path.write_text("<score-partwise/>", encoding="utf-8")

    response = client.get("/omr/jobs/ready-job/musicxml")

    assert response.status_code == 200
    assert response.content == b"<score-partwise/>"
    assert response.headers["content-type"] == "application/vnd.recordare.musicxml+xml"
    assert response.headers["content-disposition"] == 'attachment; filename="score.musicxml"'


def test_get_job_musicxml_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/omr/jobs/missing-job/musicxml")

    assert response.status_code == 404
    assert response.json() == {"detail": "MusicXML result not found"}
