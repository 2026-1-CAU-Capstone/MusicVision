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


def test_root_anchor_candidates_split_merged_root_token() -> None:
    rows = [
        SimpleNamespace(
            index=1,
            y_top=20.0,
            y_bottom=60.0,
            boundaries=[
                SimpleNamespace(x=0.0),
                SimpleNamespace(x=220.0),
            ],
        )
    ]
    token = ocr_backend.OCRToken(
        "DG",
        (40.0, 24.0, 120.0, 58.0),
        confidence=0.88,
        source="cell_ocr_root_anchor_probe",
        row_index=1,
        col_index=1,
        measure_index=1,
        region="root_anchor_scan",
    )

    anchors = ocr_backend.build_root_anchor_candidates(
        [token],
        image=np.full((140, 240, 3), 255, dtype=np.uint8),
        rows=rows,
    )

    assert [anchor.root for anchor in anchors] == ["D", "G"]
    assert [anchor.anchor_index for anchor in anchors] == [1, 2]
    assert [anchor.center_x for anchor in anchors] == [60.0, 100.0]


def test_root_anchor_candidates_use_plan_hints_over_extra_scan_letters() -> None:
    rows = [
        SimpleNamespace(
            index=1,
            y_top=20.0,
            y_bottom=60.0,
            boundaries=[
                SimpleNamespace(x=0.0),
                SimpleNamespace(x=260.0),
            ],
        )
    ]
    scan_tokens = [
        ocr_backend.OCRToken(
            "GF",
            (40.0, 24.0, 140.0, 58.0),
            confidence=0.70,
            source="cell_ocr_root_anchor_probe",
            row_index=1,
            col_index=1,
            measure_index=1,
            region="root_anchor_scan",
        ),
        ocr_backend.OCRToken(
            "G",
            (180.0, 24.0, 220.0, 58.0),
            confidence=0.96,
            source="cell_ocr_root_anchor_probe",
            row_index=1,
            col_index=1,
            measure_index=1,
            region="root_anchor_scan",
        ),
    ]
    hints = [
        {
            "measure_index": 1,
            "anchor_index": 1,
            "root": "G",
            "center_x": 74.0,
            "bbox": [70.0, 24.0, 78.0, 58.0],
            "confidence": 0.5,
            "source_text": "Ig- G",
            "source_bbox": [40.0, 24.0, 220.0, 58.0],
            "row_index": 1,
            "col_index": 1,
        },
        {
            "measure_index": 1,
            "anchor_index": 2,
            "root": "G",
            "center_x": 198.0,
            "bbox": [194.0, 24.0, 202.0, 58.0],
            "confidence": 0.5,
            "source_text": "Ig- G",
            "source_bbox": [40.0, 24.0, 220.0, 58.0],
            "row_index": 1,
            "col_index": 1,
        },
    ]

    anchors = ocr_backend.build_root_anchor_candidates(
        scan_tokens,
        image=np.full((140, 280, 3), 255, dtype=np.uint8),
        rows=rows,
        anchor_hints=hints,
    )

    assert [anchor.root for anchor in anchors] == ["G", "G"]
    assert len(anchors) == 2


def test_root_anchor_local_ocr_emits_normal_semantic_regions(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    texts = iter(["G", "b", "7"])

    class FakeReader:
        def readtext(self, _image, **kwargs):
            calls.append(kwargs)
            text = next(texts)
            return [([(1, 1), (8, 1), (8, 8), (1, 8)], text, 0.93)]

    monkeypatch.setattr(ocr_backend, "_get_reader", lambda gpu=False: FakeReader())
    monkeypatch.setattr(ocr_backend, "preprocess_for_ocr", lambda image, scale: image)

    rows = [
        SimpleNamespace(
            index=1,
            y_top=20.0,
            y_bottom=60.0,
            boundaries=[
                SimpleNamespace(x=0.0),
                SimpleNamespace(x=220.0),
            ],
        )
    ]
    anchor = ocr_backend.RootAnchorCandidate(
        measure_index=1,
        anchor_index=1,
        root="G",
        center_x=80.0,
        bbox=(60.0, 24.0, 100.0, 58.0),
        confidence=0.88,
        source_text="G",
        source_bbox=(60.0, 24.0, 100.0, 58.0),
        row_index=1,
        col_index=1,
    )

    tokens, rejects = ocr_backend.extract_chart_root_anchor_local_ocr_tokens(
        np.full((140, 240, 3), 255, dtype=np.uint8),
        rows,
        anchor_candidates=[anchor],
        ocr_scale=1.0,
        region_allowlists=ocr_backend.CHART_SEMANTIC_REGION_ALLOWLISTS,
    )

    assert rejects == []
    tokens_by_region = {token.region: token.text for token in tokens}
    assert tokens_by_region == {
        "root": "G",
        "root_accidental": "b",
        "suffix_lower_right": "7",
    }
    assert [call.get("allowlist") for call in calls] == [
        ocr_backend.CHART_ROOT_OCR_ALLOWLIST,
        ocr_backend.CHART_ACCIDENTAL_OCR_ALLOWLIST,
        ocr_backend.CHART_SUFFIX_OCR_ALLOWLIST,
    ]
