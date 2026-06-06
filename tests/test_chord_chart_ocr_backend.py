from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import pipeline.chord_charts.ocr_backend as ocr_backend


def test_chart_cell_ocr_uses_region_specific_allowlists(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeReader:
        def readtext(self, _image, **kwargs):
            calls.append(kwargs)
            return []

    monkeypatch.setattr(ocr_backend, "_get_reader", lambda gpu=False: FakeReader())
    monkeypatch.setattr(ocr_backend, "preprocess_for_ocr", lambda image, scale: image)

    rows = [
        SimpleNamespace(
            index=1,
            y_top=10.0,
            y_bottom=30.0,
            boundaries=[
                SimpleNamespace(x=0.0),
                SimpleNamespace(x=100.0),
            ],
        )
    ]

    tokens, rejects = ocr_backend.extract_chart_cell_ocr_tokens(
        np.full((80, 120, 3), 255, dtype=np.uint8),
        rows,
        ocr_scale=1.0,
        region_names=("root", "suffix_lower_right"),
        region_allowlists={
            "root": "ABC",
            "suffix_lower_right": "789",
        },
    )

    assert tokens == []
    assert rejects == []
    assert [call.get("allowlist") for call in calls] == ["ABC", "789"]


def test_chart_cell_ocr_normalizes_visual_minor_dash(monkeypatch) -> None:
    class FakeReader:
        def readtext(self, _image, **_kwargs):
            return [([(8, 8), (28, 8), (28, 18), (8, 18)], "77", 0.91)]

    monkeypatch.setattr(ocr_backend, "_get_reader", lambda gpu=False: FakeReader())
    monkeypatch.setattr(ocr_backend, "preprocess_for_ocr", lambda image, scale: image)

    rows = [
        SimpleNamespace(
            index=1,
            y_top=35.0,
            y_bottom=75.0,
            boundaries=[
                SimpleNamespace(x=0.0),
                SimpleNamespace(x=120.0),
            ],
        )
    ]
    image = np.full((140, 140, 3), 255, dtype=np.uint8)
    image[70:73, 34:50] = 0

    tokens, rejects = ocr_backend.extract_chart_cell_ocr_tokens(
        image,
        rows,
        ocr_scale=1.0,
        region_names=("suffix_lower_right",),
    )

    assert rejects == []
    assert [token.text for token in tokens] == ["-7"]
    assert tokens[0].to_dict()["debug"]["visual_normalization"] == {
        "normalizer": "visual_suffix",
        "raw_text": "77",
        "normalized_text": "-7",
        "changed": True,
    }


def test_chart_readtext_omits_allowlist_when_not_requested() -> None:
    class FakeReader:
        def __init__(self) -> None:
            self.kwargs = {}

        def readtext(self, _image, **kwargs):
            self.kwargs = kwargs
            return []

    reader = FakeReader()
    ocr_backend._read_chart_text(reader, np.full((20, 20, 3), 255, dtype=np.uint8))

    assert reader.kwargs["detail"] == 1
    assert reader.kwargs["paragraph"] is False
    assert "allowlist" not in reader.kwargs
