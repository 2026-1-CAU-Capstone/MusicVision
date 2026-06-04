from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pipeline.chords.models import ChordToken
from pipeline.chords.paddleocr_rescue import (
    PaddleOCRRescueConfig,
    maybe_apply_paddleocr_rescue,
)
import pipeline.chords.paddleocr_rescue as rescue


def test_paddleocr_rescue_off_is_noop(tmp_path: Path) -> None:
    tokens = [
        ChordToken("C7", "C7", (10.0, 20.0, 40.0, 35.0), confidence=0.80),
    ]

    result_tokens, rejects, diagnostics = maybe_apply_paddleocr_rescue(
        processed_image_path=tmp_path / "homr_processed.png",
        geometry={},
        tokens=tokens,
        rejects=[],
        output_dir=tmp_path,
        config=PaddleOCRRescueConfig(
            python_path=None,
            mode="off",
            timeout_seconds=1,
        ),
    )

    assert result_tokens == tokens
    assert rejects == []
    assert diagnostics is None


def test_paddleocr_rescue_uses_worker_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_python = tmp_path / "paddle-python.exe"
    fake_python.write_text("", encoding="utf-8")
    image_path = tmp_path / "homr_processed.png"
    image_path.write_text("", encoding="utf-8")

    def fake_run(command, **kwargs):
        response_path = Path(command[command.index("--response-json") + 1])
        response_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "tokens": [
                        {
                            "text_raw": "C7#9",
                            "text_norm": "C7#9",
                            "bbox": [10.0, 20.0, 60.0, 36.0],
                            "conf": 0.99,
                        }
                    ],
                    "paddle_rejects": [{"text": "noise"}],
                    "diagnostics": {
                        "seconds": 1.23,
                        "additions": [],
                        "replacement_candidates": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(rescue.subprocess, "run", fake_run)

    tokens, rejects, diagnostics = maybe_apply_paddleocr_rescue(
        processed_image_path=image_path,
        geometry={"coordinate_space": "homr_processed_image"},
        tokens=[
            ChordToken("C19", "C19", (10.0, 20.0, 60.0, 36.0), confidence=0.61),
        ],
        rejects=[{"text": "Cx7"}],
        output_dir=tmp_path,
        config=PaddleOCRRescueConfig(
            python_path=fake_python,
            mode="adjudicated",
            timeout_seconds=1,
        ),
    )

    request = json.loads((tmp_path / "paddleocr_rescue_request.json").read_text())
    assert request["mode"] == "adjudicated"
    assert request["baseline_diagnostics"]["accepted_tokens"][0]["text_norm"] == "C19"

    assert [token.text_norm for token in tokens] == ["C7#9"]
    assert rejects == [{"text": "Cx7"}, {"text": "noise"}]
    assert diagnostics is not None
    assert diagnostics["enabled"] is True
    assert diagnostics["mode"] == "adjudicated"
    assert diagnostics["response_file"] == "paddleocr_rescue_response.json"


def test_paddleocr_rescue_worker_failure_falls_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_python = tmp_path / "paddle-python.exe"
    fake_python.write_text("", encoding="utf-8")
    image_path = tmp_path / "homr_processed.png"
    image_path.write_text("", encoding="utf-8")
    baseline = [
        ChordToken("C7", "C7", (10.0, 20.0, 40.0, 35.0), confidence=0.80),
    ]

    def fake_run(command, **kwargs):
        response_path = Path(command[command.index("--response-json") + 1])
        response_path.write_text(
            json.dumps({"status": "failed", "error": "boom"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, stdout="out", stderr="err")

    monkeypatch.setattr(rescue.subprocess, "run", fake_run)

    tokens, rejects, diagnostics = maybe_apply_paddleocr_rescue(
        processed_image_path=image_path,
        geometry={},
        tokens=baseline,
        rejects=[],
        output_dir=tmp_path,
        config=PaddleOCRRescueConfig(
            python_path=fake_python,
            mode="additions",
            timeout_seconds=1,
        ),
    )

    assert tokens == baseline
    assert rejects == []
    assert diagnostics is not None
    assert diagnostics["enabled"] is False
    assert diagnostics["reason"] == "worker_failed"
    assert diagnostics["error"] == "boom"
