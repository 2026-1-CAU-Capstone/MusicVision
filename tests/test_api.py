from io import BytesIO
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import numpy as np
import pytest

import pipeline.run_homr as run_homr_module
import app.api.endpoints.omr as omr_endpoint
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
        input_path.with_suffix(".musicxml").write_text(
            """
            <score-partwise>
              <part id="P1">
                <measure number="1"/>
              </part>
            </score-partwise>
            """,
            encoding="utf-8",
        )
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
                        "systems": [
                            {
                                "index": 1,
                                "measures": [
                                    {
                                        "index": 1,
                                        "bbox": [10.0, 20.0, 190.0, 80.0],
                                        "chords": [],
                                    }
                                ],
                            }
                        ],
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
        "chord_assignments_path": "jobs/demo-job/output/chord_assignments.json",
        "message": "OMR processing completed",
    }

    completed = client.get("/omr/jobs/demo-job")
    assert completed.status_code == 200
    assert completed.json() == {
        "job_id": "demo-job",
        "status": "completed",
        "message": "OMR processing completed",
        "musicxml_path": "jobs/demo-job/output/score.musicxml",
        "chord_assignments_path": "jobs/demo-job/output/chord_assignments.json",
    }

    chord_assignments_payload = client.get("/omr/jobs/demo-job/chord-assignments")
    assert chord_assignments_payload.status_code == 200
    assert (
        chord_assignments_payload.json()["pages"][0]["assignment_source"]
        == "homr_geometry"
    )
    assert chord_assignments_payload.json()["overlay_file"] == "chord_assignment_overlay.png"
    assert chord_assignments_payload.json()["measure_alignment"] == {
        "status": "aligned",
        "musicxml_measure_count": 1,
        "visual_measure_count": 1,
        "musicxml_system_count": 1,
        "visual_system_count": 1,
        "aligned_system_count": 1,
        "mismatched_system_count": 0,
        "system_alignment": [
            {
                "visual_system_index": 1,
                "musicxml_system_index": 1,
                "status": "aligned",
                "musicxml_measure_count": 1,
                "visual_measure_count": 1,
            }
        ],
    }
    assert chord_assignments_payload.json()["pages"][0]["systems"][0]["measures"][0][
        "musicxml_measure_number"
    ] == "1"
    assert chord_assignments_payload.json()["chord_ocr"] == {
        "backend": "easyocr",
        "accepted_tokens": [],
        "rejected_hits": [],
        "filtered_hits": [],
    }
    assert (
        tmp_path / "jobs" / "demo-job" / "output" / "chord_assignment_overlay.png"
    ).exists()


def test_process_sheet_music_chords_returns_assignments(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_sheet_music_chord_pipeline(
        *,
        job_id: str,
        input_file_path: Path,
        intermediate_dir: Path,
        output_dir: Path,
        logs_dir: Path,
    ) -> omr_service.SheetMusicChordPipelineResult:
        chord_assignments = {
            "job_id": job_id,
            "source_file": input_file_path.name,
            "source_type": "sheet_music",
            "pipeline": "homr_geometry_only",
            "measure_alignment": {
                "status": "visual_only",
                "musicxml_measure_count": None,
                "visual_measure_count": 1,
            },
            "chord_ocr": {
                "backend": "easyocr",
                "accepted_tokens": [
                    {
                        "text_raw": "Dm7",
                        "text_norm": "Dm7",
                        "bbox": [10.0, 20.0, 40.0, 30.0],
                        "confidence": 0.91,
                    }
                ],
                "rejected_hits": [],
                "filtered_hits": [],
            },
            "pages": [
                {
                    "page": 1,
                    "assignment_source": "homr_geometry",
                    "systems": [
                        {
                            "index": 1,
                            "measures": [
                                {
                                    "index": 1,
                                    "chords": [
                                        {
                                            "text_raw": "Dm7",
                                            "text_norm": "Dm7",
                                            "beat": 1.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        chord_assignments_path = output_dir / "chord_assignments.json"
        chord_assignments_path.write_text(
            json.dumps(chord_assignments),
            encoding="utf-8",
        )

        return omr_service.SheetMusicChordPipelineResult(
            chord_assignments_path=chord_assignments_path,
        )

    monkeypatch.setattr(
        omr_endpoint,
        "run_sheet_music_chord_pipeline",
        fake_run_sheet_music_chord_pipeline,
    )

    response = client.post(
        "/chords/sheet-music/process",
        data={"job_id": "chord-only-job"},
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "chord-only-job"
    assert payload["status"] == "completed"
    assert payload["source_type"] == "sheet_music"
    assert (
        payload["chord_assignments_path"]
        == "jobs/chord-only-job/output/chord_assignments.json"
    )
    assert payload["message"] == "Sheet music chord processing completed"
    assert payload["chord_assignments"]["pages"][0]["systems"][0]["measures"][0][
        "chords"
    ] == [{"text_raw": "Dm7", "text_norm": "Dm7", "beat": 1.0}]
    assert payload["chord_assignments"]["pipeline"] == "homr_geometry_only"
    assert payload["chord_assignments"]["measure_alignment"]["status"] == "visual_only"
    assert "musicxml_path" not in payload

    completed = client.get("/omr/jobs/chord-only-job")
    assert completed.status_code == 200
    assert completed.json() == {
        "job_id": "chord-only-job",
        "status": "completed",
        "message": "Sheet music chord processing completed",
        "chord_assignments_path": "jobs/chord-only-job/output/chord_assignments.json",
    }


def test_process_sheet_music_chords_rejects_unsupported_extensions(
    client: TestClient,
) -> None:
    response = client.post(
        "/chords/sheet-music/process",
        files={"file": ("score.txt", BytesIO(b"not-supported"), "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png"
    }


def test_process_chord_chart_returns_chart(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_chord_chart_pipeline(
        *,
        job_id: str,
        input_file_path: Path,
        intermediate_dir: Path,
        output_dir: Path,
        logs_dir: Path,
    ) -> omr_service.ChordChartPipelineResult:
        chord_chart = {
            "job_id": job_id,
            "source_file": input_file_path.name,
            "source_type": "chord_chart",
            "pipeline": "chart_grid_ocr",
            "time_signature": {
                "text_raw": "4/4",
                "numerator": 4,
                "denominator": 4,
            },
            "pages": [
                {
                    "page": 1,
                    "assignment_source": "chart_grid_detection",
                    "systems": [
                        {
                            "index": 1,
                            "section": "A",
                            "measures": [
                                {
                                    "index": 1,
                                    "chords": [
                                        {
                                            "text_raw": "Ab-7b5",
                                            "text_norm": "Abm7b5",
                                            "beat": 1,
                                        }
                                    ],
                                    "symbols": [],
                                }
                            ],
                        }
                    ],
                }
            ],
            "flow": {
                "repeat_groups": [],
                "endings": [],
                "navigation": [],
            },
            "chart_ocr": {
                "backend": "easyocr",
                "accepted_tokens": [],
                "rejected_hits": [],
                "unassigned_tokens": [],
                "detected_symbols": [],
            },
            "warnings": [],
        }
        chord_chart_path = output_dir / "chord_chart.json"
        chord_chart_path.write_text(json.dumps(chord_chart), encoding="utf-8")
        return omr_service.ChordChartPipelineResult(chord_chart_path=chord_chart_path)

    monkeypatch.setattr(
        omr_endpoint,
        "run_chord_chart_pipeline",
        fake_run_chord_chart_pipeline,
    )

    response = client.post(
        "/chords/chart/process",
        data={"job_id": "chart-job"},
        files={"file": ("chart.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "chart-job"
    assert payload["status"] == "completed"
    assert payload["source_type"] == "chord_chart"
    assert payload["chord_chart_path"] == "jobs/chart-job/output/chord_chart.json"
    assert payload["chord_chart"]["source_type"] == "chord_chart"
    assert (
        payload["chord_chart"]["pages"][0]["systems"][0]["measures"][0]["chords"][0][
            "text_norm"
        ]
        == "Abm7b5"
    )

    completed = client.get("/omr/jobs/chart-job")
    assert completed.status_code == 200
    assert completed.json() == {
        "job_id": "chart-job",
        "status": "completed",
        "message": "Chord chart processing completed",
        "chord_chart_path": "jobs/chart-job/output/chord_chart.json",
    }

    chart_file = client.get("/omr/jobs/chart-job/chord-chart")
    assert chart_file.status_code == 200
    assert chart_file.json()["source_type"] == "chord_chart"
    assert chart_file.headers["content-type"] == "application/json"


def test_process_chord_chart_rejects_existing_job_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    existing_job_dir = tmp_path / "jobs" / "chart-job"
    existing_job_dir.mkdir(parents=True)
    pipeline_called = False

    def fake_run_chord_chart_pipeline(**_kwargs: object) -> None:
        nonlocal pipeline_called
        pipeline_called = True

    monkeypatch.setattr(
        omr_endpoint,
        "run_chord_chart_pipeline",
        fake_run_chord_chart_pipeline,
    )

    response = client.post(
        "/chords/chart/process",
        data={"job_id": "chart-job"},
        files={"file": ("chart.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "job_id already exists. Use a new job_id to preserve existing "
            "job artifacts."
        )
    }
    assert pipeline_called is False


def test_process_omr_rejects_unsupported_extensions(client: TestClient) -> None:
    response = client.post(
        "/omr/process",
        files={"file": ("score.txt", BytesIO(b"not-supported"), "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported file extension. Allowed extensions: .jpeg, .jpg, .png"
    }


def test_dev_process_omr_rejects_invalid_callback_url(client: TestClient) -> None:
    response = client.post(
        "/omr/dev/process",
        data={"callback_url": "not-a-url"},
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "callback_url must be an absolute http(s) URL."
    }


def test_prod_process_omr_rejects_untrusted_callback_host(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(
        omr_endpoint,
        "OMR_CALLBACK_URL",
        "https://backend.example/fixed-omr-callback",
    )

    response = client.post(
        "/omr/prod/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        data={"callback_url": "https://requestor.example/omr-callback"},
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "callback_url host is not allowed. "
            "It must match the configured OMR_CALLBACK_URL host."
        )
    }


def test_prod_process_omr_uses_domain_validated_request_callback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_omr_pipeline(**_kwargs) -> None:
        raise RuntimeError("pipeline failed")

    callbacks: list[tuple[str, dict[str, object]]] = []

    def fake_post_job_callback(
        callback_url: str,
        payload: dict[str, object],
    ) -> None:
        callbacks.append((callback_url, payload))

    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(
        omr_endpoint,
        "OMR_CALLBACK_URL",
        "https://backend.example/fixed-omr-callback",
    )
    monkeypatch.setattr(omr_endpoint, "run_omr_pipeline", fake_run_omr_pipeline)
    monkeypatch.setattr(omr_endpoint, "_post_job_callback", fake_post_job_callback)

    response = client.post(
        "/omr/prod/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        data={
            "job_id": "fixed-callback-job",
            "callback_url": "https://backend.example/custom-omr-callback",
        },
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 202
    assert callbacks == [
        (
            "https://backend.example/custom-omr-callback",
            {
                "job_id": "fixed-callback-job",
                "status": "failed",
                "message": "OMR processing failed",
                "error": "pipeline failed",
            },
        )
    ]


def test_prod_process_omr_requires_api_key_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", None)
    monkeypatch.setattr(
        omr_endpoint,
        "OMR_CALLBACK_URL",
        "https://backend.example/fixed-omr-callback",
    )

    response = client.post(
        "/omr/prod/process",
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "OMR API key is not configured."}


def test_prod_process_omr_requires_request_callback_url(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(
        omr_endpoint,
        "OMR_CALLBACK_URL",
        "https://backend.example/fixed-omr-callback",
    )

    response = client.post(
        "/omr/prod/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "callback_url is required by the production OMR endpoint."
    }


def test_prod_process_omr_requires_configured_callback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(omr_endpoint, "OMR_CALLBACK_URL", None)

    response = client.post(
        "/omr/prod/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "OMR_CALLBACK_URL is not configured."}


def test_dev_process_chord_chart_requires_api_key_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", None)

    response = client.post(
        "/chords/chart/dev/process",
        files={"file": ("chart.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "OMR API key is not configured."}


def test_dev_process_chord_chart_records_failed_background_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_chord_chart_pipeline(**_kwargs: object) -> None:
        raise RuntimeError("chart pipeline failed")

    callbacks: list[tuple[str, dict[str, object]]] = []

    def fake_post_job_callback(
        callback_url: str,
        payload: dict[str, object],
    ) -> None:
        callbacks.append((callback_url, payload))

    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(
        omr_endpoint,
        "run_chord_chart_pipeline",
        fake_run_chord_chart_pipeline,
    )
    monkeypatch.setattr(omr_endpoint, "_post_job_callback", fake_post_job_callback)

    response = client.post(
        "/chords/chart/dev/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        data={
            "job_id": "failed-chart-job",
            "callback_url": "https://backend.example/chart-callbacks",
        },
        files={"file": ("chart.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": "failed-chart-job",
        "status": "queued",
        "message": "Chord chart processing queued",
    }

    failed = client.get(
        "/omr/jobs/failed-chart-job",
        headers={"X-OMR-API-Key": "omr-secret"},
    )
    assert failed.status_code == 200
    assert failed.json() == {
        "job_id": "failed-chart-job",
        "status": "failed",
        "message": "Chord chart processing failed",
        "error": "chart pipeline failed",
    }
    assert callbacks == [
        (
            "https://backend.example/chart-callbacks",
            {
                "job_id": "failed-chart-job",
                "status": "failed",
                "message": "Chord chart processing failed",
                "error": "chart pipeline failed",
            },
        )
    ]


def test_prod_process_chord_chart_rejects_untrusted_callback_host(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(
        omr_endpoint,
        "OMR_CALLBACK_URL",
        "https://backend.example/fixed-omr-callback",
    )

    response = client.post(
        "/chords/chart/prod/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        data={"callback_url": "https://other.example/chart-callback"},
        files={"file": ("chart.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "callback_url host is not allowed. "
            "It must match the configured OMR_CALLBACK_URL host."
        )
    }


def test_prod_process_chord_chart_uses_domain_validated_request_callback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callbacks: list[tuple[str, dict[str, object]]] = []

    def fake_run_chord_chart_pipeline(
        *,
        job_id: str,
        input_file_path: Path,
        intermediate_dir: Path,
        output_dir: Path,
        logs_dir: Path,
    ) -> omr_service.ChordChartPipelineResult:
        chord_chart_path = output_dir / "chord_chart.json"
        chord_chart_path.write_text('{"source_type":"chord_chart"}', encoding="utf-8")
        return omr_service.ChordChartPipelineResult(chord_chart_path=chord_chart_path)

    def fake_post_job_callback(
        callback_url: str,
        payload: dict[str, object],
    ) -> None:
        callbacks.append((callback_url, payload))

    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")
    monkeypatch.setattr(
        omr_endpoint,
        "OMR_CALLBACK_URL",
        "https://backend.example/fixed-omr-callback",
    )
    monkeypatch.setattr(
        omr_endpoint,
        "run_chord_chart_pipeline",
        fake_run_chord_chart_pipeline,
    )
    monkeypatch.setattr(omr_endpoint, "_post_job_callback", fake_post_job_callback)

    response = client.post(
        "/chords/chart/prod/process",
        headers={"X-OMR-API-Key": "omr-secret"},
        data={
            "job_id": "callback-chart-job",
            "callback_url": "https://backend.example/chart-callback",
        },
        files={"file": ("chart.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": "callback-chart-job",
        "status": "queued",
        "message": "Chord chart processing queued",
    }
    assert callbacks == [
        (
            "https://backend.example/chart-callback",
            {
                "job_id": "callback-chart-job",
                "status": "completed",
                "message": "Chord chart processing completed",
                "chord_chart_path": "jobs/callback-chart-job/output/chord_chart.json",
            },
        )
    ]


def test_omr_api_key_is_required_when_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(omr_endpoint, "OMR_API_KEY", "omr-secret")

    unauthorized = client.get("/omr/jobs/missing-job")
    authorized = client.get(
        "/omr/jobs/missing-job",
        headers={"X-OMR-API-Key": "omr-secret"},
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Invalid OMR API key."}
    assert authorized.status_code == 200
    assert authorized.json() == {"job_id": "missing-job", "status": "not_found"}


def test_callback_api_key_header_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}

    class FakeCallbackResponse:
        status = 204

        def __enter__(self) -> "FakeCallbackResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(
        request: object,
        *,
        timeout: int,
    ) -> FakeCallbackResponse:
        assert timeout == 10
        captured_headers.update(dict(request.header_items()))
        return FakeCallbackResponse()

    monkeypatch.setattr(omr_endpoint, "OMR_CALLBACK_API_KEY", "callback-secret")
    monkeypatch.setattr(omr_endpoint.url_request, "urlopen", fake_urlopen)

    callback_error = omr_endpoint._post_job_callback(
        "https://backend.example/fixed-omr-callback",
        {"job_id": "demo-job", "status": "completed"},
    )

    assert callback_error is None
    assert captured_headers["X-omr-callback-api-key"] == "callback-secret"


def test_dev_process_omr_records_failed_background_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_omr_pipeline(**_kwargs) -> None:
        raise RuntimeError("pipeline failed")

    callbacks: list[tuple[str, dict[str, object]]] = []

    def fake_post_job_callback(
        callback_url: str,
        payload: dict[str, object],
    ) -> None:
        callbacks.append((callback_url, payload))

    monkeypatch.setattr(omr_endpoint, "run_omr_pipeline", fake_run_omr_pipeline)
    monkeypatch.setattr(omr_endpoint, "_post_job_callback", fake_post_job_callback)

    response = client.post(
        "/omr/dev/process",
        data={
            "job_id": "failed-job",
            "callback_url": "https://backend.example/omr-callbacks",
        },
        files={"file": ("score.png", BytesIO(b"fake-image"), "image/png")},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": "failed-job",
        "status": "queued",
        "message": "OMR processing queued",
    }

    failed = client.get("/omr/jobs/failed-job")
    assert failed.status_code == 200
    assert failed.json() == {
        "job_id": "failed-job",
        "status": "failed",
        "message": "OMR processing failed",
        "error": "pipeline failed",
    }
    assert callbacks == [
        (
            "https://backend.example/omr-callbacks",
            {
                "job_id": "failed-job",
                "status": "failed",
                "message": "OMR processing failed",
                "error": "pipeline failed",
            },
        )
    ]


def test_job_status_reports_processing_and_missing(client: TestClient, tmp_path) -> None:
    processing_job_dir = tmp_path / "jobs" / "pending-job"
    processing_job_dir.mkdir(parents=True)

    processing = client.get("/omr/jobs/pending-job")
    missing = client.get("/omr/jobs/missing-job")

    assert processing.status_code == 200
    assert processing.json() == {
        "job_id": "pending-job",
        "status": "processing",
        "message": "OMR processing in progress",
    }
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


def test_get_job_chord_assignments_returns_file(client: TestClient, tmp_path: Path) -> None:
    assignments_path = (
        tmp_path / "jobs" / "ready-job" / "output" / "chord_assignments.json"
    )
    assignments_path.parent.mkdir(parents=True)
    assignments_path.write_text('{"job_id":"ready-job"}', encoding="utf-8")

    response = client.get("/omr/jobs/ready-job/chord-assignments")

    assert response.status_code == 200
    assert response.json() == {"job_id": "ready-job"}
    assert response.headers["content-type"] == "application/json"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="chord_assignments.json"'
    )


def test_get_job_chord_assignments_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/omr/jobs/missing-job/chord-assignments")

    assert response.status_code == 404
    assert response.json() == {"detail": "Chord assignments not found"}


def test_get_job_chord_chart_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/omr/jobs/missing-job/chord-chart")

    assert response.status_code == 404
    assert response.json() == {"detail": "Chord chart not found"}
