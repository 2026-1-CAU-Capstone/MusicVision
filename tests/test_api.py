from io import BytesIO
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import numpy as np
import pytest

import pipeline.run_homr as run_homr_module
import app.services.omr_service as omr_service


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_omr_creates_outputs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
        geometry_path = Path(command[4])
        processed_image_path = Path(command[6])
        geometry_path.write_text(
            """
            {
              "coordinate_space": "homr_processed_image",
              "image": {"width": 200, "height": 100},
              "systems": [],
              "barlines": []
            }
            """,
            encoding="utf-8",
        )
        processed_image_path.write_bytes(b"fake-image")
        assert env["PYTHONUTF8"] == "1"
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="Finished parsing 1 staves\n",
        )

    monkeypatch.setattr(run_homr_module.subprocess, "run", fake_homr_run)
    monkeypatch.setattr(
        omr_service,
        "load_rgb_image",
        lambda _path: np.zeros((100, 200, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        omr_service,
        "extract_chord_tokens_ocr",
        lambda _image: ([], []),
    )
    monkeypatch.setattr(
        omr_service,
        "assign_chords_to_measures",
        lambda **_kwargs: {
            "source": "homr_processed.png",
            "time_signature": "4/4",
            "beats_per_bar": 4,
            "pages": [
                {
                    "page": 1,
                    "width": 200.0,
                    "height": 100.0,
                    "assignment_source": "homr_geometry",
                    "systems": [],
                }
            ],
        },
    )

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

    result_payload = client.get("/omr/jobs/demo-job/result")
    assert result_payload.status_code == 200
    assert result_payload.json()["pages"][0]["assignment_source"] == "homr_geometry"
    assert result_payload.json()["overlay_file"] == "chord_assignment_overlay.png"
    assert result_payload.json()["chord_ocr"] == {
        "backend": "easyocr",
        "accepted_tokens": [],
        "rejected_hits": [],
        "filtered_hits": [],
    }
    assert (
        tmp_path / "jobs" / "demo-job" / "output" / "chord_assignment_overlay.png"
    ).exists()


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


def test_get_job_result_returns_file(client: TestClient, tmp_path: Path) -> None:
    result_path = tmp_path / "jobs" / "ready-job" / "output" / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text('{"job_id":"ready-job"}', encoding="utf-8")

    response = client.get("/omr/jobs/ready-job/result")

    assert response.status_code == 200
    assert response.json() == {"job_id": "ready-job"}
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="result.json"'


def test_get_job_result_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/omr/jobs/missing-job/result")

    assert response.status_code == 404
    assert response.json() == {"detail": "Structured result not found"}
