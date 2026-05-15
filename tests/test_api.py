from io import BytesIO

from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_omr_creates_outputs(client: TestClient) -> None:
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
        "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .pdf, .png"
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
