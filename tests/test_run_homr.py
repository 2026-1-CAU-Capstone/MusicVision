from pathlib import Path
import subprocess

import pytest

import pipeline.run_homr as run_homr_module


def test_run_homr_invokes_cli_and_moves_musicxml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preprocessed_input_path = tmp_path / "intermediate" / "preprocessed.png"
    preprocessed_input_path.parent.mkdir()
    preprocessed_input_path.write_bytes(b"fake-image")

    output_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert command[:3] == [run_homr_module.sys.executable, "-m", "homr.main"]
        assert command[3:5] == ["--geometry-json", str((output_dir / "geometry.json").resolve())]
        assert command[5:7] == [
            "--processed-image",
            str((output_dir / "homr_processed.png").resolve()),
        ]
        assert Path(command[-1]) == preprocessed_input_path.resolve()
        assert cwd == run_homr_module.HOMR_PROJECT_DIR
        assert capture_output is True
        assert text is True
        assert check is False
        assert env["PYTHONUTF8"] == "1"

        preprocessed_input_path.with_suffix(".musicxml").write_text(
            "<score-partwise/>",
            encoding="utf-8",
        )
        (output_dir / "geometry.json").write_text(
            '{"coordinate_space":"homr_processed_image"}',
            encoding="utf-8",
        )
        (output_dir / "homr_processed.png").write_bytes(b"fake-processed-image")
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="homr stdout\n",
            stderr="homr stderr\n",
        )

    monkeypatch.setattr(run_homr_module.subprocess, "run", fake_run)

    artifacts = run_homr_module.run_homr(
        preprocessed_input_path=preprocessed_input_path,
        output_dir=output_dir,
        logs_dir=logs_dir,
    )

    assert artifacts.musicxml_path == output_dir / "score.musicxml"
    assert artifacts.geometry_json_path == output_dir / "geometry.json"
    assert artifacts.processed_image_path == output_dir / "homr_processed.png"
    assert artifacts.musicxml_path.read_text(encoding="utf-8") == "<score-partwise/>"
    assert not preprocessed_input_path.with_suffix(".musicxml").exists()

    log_text = (logs_dir / "homr.log").read_text(encoding="utf-8")
    assert "homr stdout" in log_text
    assert "homr stderr" in log_text


def test_run_homr_raises_when_cli_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preprocessed_input_path = tmp_path / "intermediate" / "preprocessed.png"
    preprocessed_input_path.parent.mkdir()
    preprocessed_input_path.write_bytes(b"fake-image")

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=2,
            stdout="",
            stderr="unsupported image\n",
        )

    monkeypatch.setattr(run_homr_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="HOMR failed with exit code 2"):
        run_homr_module.run_homr(
            preprocessed_input_path=preprocessed_input_path,
            output_dir=tmp_path / "output",
            logs_dir=tmp_path / "logs",
        )

    log_text = (tmp_path / "logs" / "homr.log").read_text(encoding="utf-8")
    assert "unsupported image" in log_text
