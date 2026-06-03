from __future__ import annotations

import numpy as np

import pipeline.chords.easyocr_backend as ocr_backend
from pipeline.chords.models import ChordToken


def _geometry(system_count: int = 4) -> dict:
    systems = []
    barlines = []
    for index in range(system_count):
        y0 = 80 + index * 90
        y1 = y0 + 50
        systems.append(
            {
                "index": index + 1,
                "bbox": [40.0, float(y0), 360.0, float(y1)],
            }
        )
        for x in (80.0, 160.0, 240.0, 320.0):
            barlines.append(
                {
                    "bbox": [x - 1.0, float(y0), x + 1.0, float(y1)],
                    "center": [x, float((y0 + y1) / 2.0)],
                }
            )

    return {
        "coordinate_space": "homr_processed_image",
        "image": {"width": 400, "height": 420},
        "systems": systems,
        "barlines": barlines,
    }


def test_chord_band_regions_crop_above_each_system() -> None:
    image = np.full((420, 400, 3), 255, dtype=np.uint8)
    regions = ocr_backend._chord_band_regions(
        image=image,
        geometry=_geometry(system_count=2),
    )

    assert len(regions) == 2
    first = regions[0]
    assert first.source == "targeted_chord_band"
    assert first.system_index == 1
    assert first.bbox[0] < 40
    assert first.bbox[2] > 360
    assert first.bbox[1] < 80
    assert first.bbox[3] <= 88


def test_targeted_fallback_reason_uses_conservative_sparsity_thresholds() -> None:
    tokens = [
        ChordToken("C7", "C7", (50.0, 30.0, 80.0, 45.0), confidence=0.80),
    ]

    assert (
        ocr_backend._targeted_fallback_reason(
            targeted_tokens=[],
            systems_total=4,
            usable_system_crop_count=4,
            systems_with_chords=0,
            estimated_visual_measures=16,
        )
        == "no_targeted_chord_tokens"
    )
    assert (
        ocr_backend._targeted_fallback_reason(
            targeted_tokens=tokens,
            systems_total=4,
            usable_system_crop_count=1,
            systems_with_chords=1,
            estimated_visual_measures=16,
        )
        == "insufficient_target_region_coverage"
    )
    assert (
        ocr_backend._targeted_fallback_reason(
            targeted_tokens=tokens,
            systems_total=4,
            usable_system_crop_count=4,
            systems_with_chords=1,
            estimated_visual_measures=16,
        )
        == "too_few_chord_tokens_per_measure"
    )

    assert (
        ocr_backend._targeted_fallback_reason(
            targeted_tokens=[
                ChordToken("C7", "C7", (50.0, 30.0, 80.0, 45.0), confidence=0.80),
                ChordToken("Dm7", "Dm7", (120.0, 30.0, 155.0, 45.0), confidence=0.80),
                ChordToken("G7", "G7", (210.0, 30.0, 240.0, 45.0), confidence=0.80),
                ChordToken("Cmaj7", "Cmaj7", (300.0, 30.0, 350.0, 45.0), confidence=0.80),
            ],
            systems_total=4,
            usable_system_crop_count=4,
            systems_with_chords=2,
            estimated_visual_measures=16,
        )
        is None
    )


def test_sparse_targeted_ocr_falls_back_to_full_page_and_merges(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_run_ocr_pass(
        _image,
        *,
        source: str,
        system_index: int | None = None,
        **_kwargs,
    ) -> ocr_backend.OCRPassResult:
        calls.append(source)
        if source == "targeted_chord_band" and system_index == 1:
            return ocr_backend.OCRPassResult(
                tokens=[
                    ChordToken(
                        "C7",
                        "C7",
                        (90.0, 45.0, 120.0, 62.0),
                        confidence=0.40,
                    )
                ],
                rejects=[],
            )
        if source == "full_page":
            return ocr_backend.OCRPassResult(
                tokens=[
                    ChordToken(
                        "C7",
                        "C7",
                        (90.0, 45.0, 120.0, 62.0),
                        confidence=0.92,
                    ),
                    ChordToken(
                        "Dm7",
                        "Dm7",
                        (170.0, 45.0, 210.0, 62.0),
                        confidence=0.88,
                    ),
                ],
                rejects=[],
            )
        return ocr_backend.OCRPassResult(tokens=[], rejects=[])

    monkeypatch.setattr(ocr_backend, "_run_ocr_pass", fake_run_ocr_pass)

    tokens, rejects, strategy = ocr_backend.extract_chord_tokens_ocr(
        np.full((420, 400, 3), 255, dtype=np.uint8),
        geometry=_geometry(system_count=4),
        return_strategy=True,
    )

    assert rejects == []
    assert calls.count("targeted_chord_band") == 4
    assert calls.count("full_page") == 1
    assert strategy["mode"] == "targeted_with_full_page_fallback"
    assert strategy["fallback"]["reason"] == "too_few_chord_tokens_per_measure"
    assert [(token.text_norm, token.confidence) for token in tokens] == [
        ("C7", 0.92),
        ("Dm7", 0.88),
    ]


def test_complete_targeted_ocr_skips_full_page_fallback(monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_ocr_pass(
        _image,
        *,
        source: str,
        system_index: int | None = None,
        **_kwargs,
    ) -> ocr_backend.OCRPassResult:
        calls.append(source)
        return ocr_backend.OCRPassResult(
            tokens=[
                ChordToken(
                    f"C{system_index}",
                    f"C{system_index}",
                    (90.0, 45.0 + float(system_index or 0) * 90.0, 120.0, 62.0),
                    confidence=0.80,
                )
            ],
            rejects=[],
        )

    monkeypatch.setattr(ocr_backend, "_run_ocr_pass", fake_run_ocr_pass)

    tokens, _rejects, strategy = ocr_backend.extract_chord_tokens_ocr(
        np.full((420, 400, 3), 255, dtype=np.uint8),
        geometry=_geometry(system_count=4),
        return_strategy=True,
    )

    assert calls == ["targeted_chord_band"] * 4
    assert strategy["mode"] == "targeted_only"
    assert strategy["fallback"]["triggered"] is False
    assert len(tokens) == 4


def test_readtext_uses_chord_character_allowlist() -> None:
    class FakeReader:
        def __init__(self) -> None:
            self.kwargs = {}

        def readtext(self, _image, **kwargs):
            self.kwargs = kwargs
            return []

    reader = FakeReader()
    ocr_backend._readtext(reader, np.full((20, 20, 3), 255, dtype=np.uint8))

    assert reader.kwargs["detail"] == 1
    assert reader.kwargs["paragraph"] is False
    assert "_" in reader.kwargs["allowlist"]
    assert "-" in reader.kwargs["allowlist"]
    assert "T" not in reader.kwargs["allowlist"]


def test_rejected_near_chord_reports_uncertain_candidate_context(monkeypatch) -> None:
    monkeypatch.setattr(ocr_backend, "preprocess_for_ocr", lambda image, scale: image)
    monkeypatch.setattr(ocr_backend, "_get_reader", lambda gpu=False: object())
    monkeypatch.setattr(
        ocr_backend,
        "_readtext",
        lambda _reader, _image: [
            (
                [(10.0, 10.0), (40.0, 10.0), (40.0, 25.0), (10.0, 25.0)],
                "Cx7",
                0.88,
            )
        ],
    )

    result = ocr_backend._run_ocr_pass(
        np.full((40, 60, 3), 255, dtype=np.uint8),
        min_confidence=0.15,
        gpu=False,
        ocr_scale=1.0,
        source="targeted_chord_band",
        system_index=1,
    )

    assert result.tokens == []
    assert result.rejects == [
        {
            "text": "Cx7",
            "text_norm": "Cx7",
            "bbox": [10.0, 10.0, 40.0, 25.0],
            "conf": 0.88,
            "source": "targeted_chord_band",
            "system_index": 1,
            "reason": "failed chord grammar",
            "candidate_kind": "uncertain_chord",
            "suggestions": [
                {
                    "text_norm": "C7",
                    "score": 0.733,
                    "reason": "near_valid_chord_candidate",
                },
                {
                    "text_norm": "C+7",
                    "score": 0.667,
                    "reason": "near_valid_chord_candidate",
                },
                {
                    "text_norm": "C-7",
                    "score": 0.667,
                    "reason": "near_valid_chord_candidate",
                },
            ],
        }
    ]
