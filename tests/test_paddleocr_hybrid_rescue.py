from __future__ import annotations

from pipeline.chords.models import ChordToken
from scripts import paddleocr_hybrid_chord_rescue as hybrid


def _hit(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    score: float = 0.80,
    system_index: int = 1,
) -> dict:
    return {
        "text": text,
        "score": score,
        "bbox": list(bbox),
        "system_index": system_index,
    }


def test_fragment_merge_combines_root_and_altered_suffix() -> None:
    merged, consumed, records = hybrid.merge_fragment_hits(
        [
            _hit("C", (100.0, 50.0, 124.0, 78.0)),
            _hit("7#9", (126.0, 50.0, 178.0, 78.0)),
            _hit("E", (220.0, 50.0, 244.0, 78.0)),
            _hit("7#5", (246.0, 50.0, 298.0, 78.0)),
        ]
    )

    assert {hit["text"] for hit in merged} == {"C7#9", "E7#5"}
    assert len(consumed) == 4
    assert [record["text"] for record in records] == ["C7#9", "E7#5"]


def test_fragment_merge_rejects_distant_or_cross_system_fragments() -> None:
    assert hybrid.merge_fragment_candidate(
        _hit("C", (100.0, 50.0, 124.0, 78.0)),
        _hit("7#9", (240.0, 50.0, 292.0, 78.0)),
    ) is None
    assert hybrid.merge_fragment_candidate(
        _hit("C", (100.0, 50.0, 124.0, 78.0), system_index=1),
        _hit("7#9", (126.0, 50.0, 178.0, 78.0), system_index=2),
    ) is None


def test_rescue_regions_include_uncertain_rejects_and_high_risk_accepted_tokens() -> None:
    regions = hybrid.build_rescue_regions(
        image_shape=(300, 400, 3),
        baseline_diagnostics={
            "rejected_hits": [
                {
                    "text": "Cx7",
                    "text_norm": "Cx7",
                    "bbox": [50.0, 60.0, 100.0, 90.0],
                    "conf": 0.88,
                    "system_index": 1,
                    "candidate_kind": "uncertain_chord",
                }
            ],
            "accepted_tokens": [
                {
                    "text_raw": "C79",
                    "text_norm": "C79",
                    "bbox": [180.0, 60.0, 230.0, 90.0],
                    "conf": 0.62,
                    "system_index": 1,
                },
                {
                    "text_raw": "F-7",
                    "text_norm": "F-7",
                    "bbox": [280.0, 60.0, 330.0, 90.0],
                    "conf": 0.95,
                    "system_index": 1,
                },
            ],
        },
        accepted_confidence_threshold=0.50,
        padding_x=10,
        padding_y=8,
    )

    assert len(regions) == 2
    assert [trigger["text_norm"] for region in regions for trigger in region.triggers] == [
        "Cx7",
        "C79",
    ]


def test_hybrid_reports_replacement_candidates_without_applying_by_default() -> None:
    baseline_tokens = [
        ChordToken(
            "C79",
            "C79",
            (100.0, 50.0, 160.0, 82.0),
            confidence=0.62,
            system_index=1,
        ),
        ChordToken(
            "F-7",
            "F-7",
            (220.0, 50.0, 280.0, 82.0),
            confidence=0.93,
            system_index=1,
        ),
    ]
    paddle_tokens = [
        ChordToken(
            "C7b9",
            "C7b9",
            (102.0, 51.0, 162.0, 83.0),
            confidence=0.80,
            system_index=1,
        ),
        ChordToken(
            "Fmaj7",
            "Fmaj7",
            (221.0, 51.0, 281.0, 83.0),
            confidence=0.96,
            system_index=1,
        ),
    ]

    result = hybrid.build_hybrid_tokens(
        baseline_tokens=baseline_tokens,
        paddle_tokens=paddle_tokens,
        accepted_confidence_threshold=0.50,
    )

    assert sorted(token.text_norm for token in result["tokens"]) == ["C79", "F-7"]
    assert len(result["replacement_candidates"]) == 2
    assert result["replacements_applied"] == []


def test_hybrid_optional_replacements_require_same_root_high_risk_baseline() -> None:
    result = hybrid.build_hybrid_tokens(
        baseline_tokens=[
            ChordToken(
                "C79",
                "C79",
                (100.0, 50.0, 160.0, 82.0),
                confidence=0.62,
                system_index=1,
            ),
            ChordToken(
                "F-7",
                "F-7",
                (220.0, 50.0, 280.0, 82.0),
                confidence=0.93,
                system_index=1,
            ),
        ],
        paddle_tokens=[
            ChordToken(
                "C7b9",
                "C7b9",
                (102.0, 51.0, 162.0, 83.0),
                confidence=0.80,
                system_index=1,
            ),
            ChordToken(
                "Gmaj7",
                "Gmaj7",
                (221.0, 51.0, 281.0, 83.0),
                confidence=0.96,
                system_index=1,
            ),
        ],
        accepted_confidence_threshold=0.50,
        apply_replacements=True,
    )

    assert sorted(token.text_norm for token in result["tokens"]) == ["C7b9", "F-7"]
    assert len(result["replacement_candidates"]) == 2
    assert len(result["replacements_applied"]) == 1


def test_hybrid_suppresses_root_only_and_uncommon_paddle_additions() -> None:
    result = hybrid.build_hybrid_tokens(
        baseline_tokens=[],
        paddle_tokens=[
            ChordToken(
                "E",
                "E",
                (100.0, 50.0, 130.0, 82.0),
                confidence=0.99,
                system_index=1,
            ),
            ChordToken(
                "E-765",
                "E-765",
                (150.0, 50.0, 210.0, 82.0),
                confidence=0.90,
                system_index=1,
            ),
            ChordToken(
                "B7#9",
                "B7#9",
                (250.0, 50.0, 320.0, 82.0),
                confidence=0.87,
                system_index=1,
            ),
        ],
        accepted_confidence_threshold=0.50,
    )

    assert [token.text_norm for token in result["tokens"]] == ["B7#9"]
    assert [token["text_norm"] for token in result["suppressed_additions"]] == [
        "E",
        "E-765",
    ]
