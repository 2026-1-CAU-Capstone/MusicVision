from __future__ import annotations

from pathlib import Path

import numpy as np

import pipeline.preprocess as preprocess


def test_preprocess_copies_non_webp_upload(tmp_path: Path) -> None:
    source = tmp_path / "score.jpg"
    source.write_bytes(b"jpeg-bytes")

    result = preprocess.preprocess_input(
        input_file_path=source,
        intermediate_dir=tmp_path / "intermediate",
    )

    assert result.name == "preprocessed.jpg"
    assert result.read_bytes() == b"jpeg-bytes"


def test_preprocess_converts_webp_upload_to_png(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "score.webp"
    source.write_bytes(b"webp-bytes")
    captured = {}

    def fake_imread(path: str, flags: int):
        captured["imread"] = (path, flags)
        return np.zeros((12, 20, 4), dtype=np.uint8)

    def fake_imwrite(path: str, image) -> bool:
        captured["imwrite"] = (path, image.shape)
        Path(path).write_bytes(b"png-bytes")
        return True

    monkeypatch.setattr(preprocess.cv2, "imread", fake_imread)
    monkeypatch.setattr(preprocess.cv2, "imwrite", fake_imwrite)

    result = preprocess.preprocess_input(
        input_file_path=source,
        intermediate_dir=tmp_path / "intermediate",
    )

    assert result.name == "preprocessed.png"
    assert result.read_bytes() == b"png-bytes"
    assert captured["imread"] == (str(source), preprocess.cv2.IMREAD_UNCHANGED)
    assert captured["imwrite"] == (str(result), (12, 20, 4))


def test_preprocess_rejects_undecodable_webp(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "score.webp"
    source.write_bytes(b"not-webp")
    monkeypatch.setattr(preprocess.cv2, "imread", lambda _path, _flags: None)

    try:
        preprocess.preprocess_input(
            input_file_path=source,
            intermediate_dir=tmp_path / "intermediate",
        )
    except RuntimeError as exc:
        assert "Could not decode WebP upload" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for undecodable WebP")
