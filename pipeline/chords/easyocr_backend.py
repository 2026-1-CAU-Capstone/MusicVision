from __future__ import annotations

from typing import Any

import numpy as np

from pipeline.chords.grammar import looks_like_chord_ocr, normalize_text
from pipeline.chords.models import ChordToken
from pipeline.chords.ocr_common import preprocess_for_ocr, try_split_merged_token


_reader: Any | None = None


def _get_reader(*, gpu: bool = False) -> Any:
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(["en"], gpu=gpu)
    return _reader


def extract_chord_tokens_ocr(
    image: np.ndarray,
    *,
    min_confidence: float = 0.15,
    gpu: bool = False,
    ocr_scale: float = 2.0,
) -> tuple[list[ChordToken], list[dict]]:
    processed = preprocess_for_ocr(image, scale=ocr_scale)
    reader = _get_reader(gpu=gpu)
    results = reader.readtext(processed, detail=1, paragraph=False)
    inverse_scale = 1.0 / ocr_scale

    tokens: list[ChordToken] = []
    rejects: list[dict] = []

    for points, text, confidence in results:
        raw_text = (text or "").strip()
        if not raw_text:
            continue

        xs = [point[0] * inverse_scale for point in points]
        ys = [point[1] * inverse_scale for point in points]
        bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))

        if confidence < min_confidence:
            rejects.append(
                {
                    "text": raw_text,
                    "bbox": bbox,
                    "conf": confidence,
                    "reason": (
                        f"confidence {confidence:.2f} < threshold {min_confidence:.2f}"
                    ),
                }
            )
            continue

        passed, corrected = looks_like_chord_ocr(raw_text)
        if passed:
            tokens.append(
                ChordToken(
                    text_raw=raw_text,
                    text_norm=normalize_text(corrected),
                    bbox=bbox,
                )
            )
            continue

        split_tokens = try_split_merged_token(raw_text, bbox)
        if split_tokens:
            tokens.extend(split_tokens)
            continue

        rejects.append(
            {
                "text": raw_text,
                "text_norm": corrected,
                "bbox": bbox,
                "conf": confidence,
                "reason": "failed chord grammar",
            }
        )

    tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return tokens, rejects
