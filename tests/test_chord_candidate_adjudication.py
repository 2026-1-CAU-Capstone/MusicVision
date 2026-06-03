from __future__ import annotations

from scripts.chord_candidate_adjudication import (
    Candidate,
    CandidateGroup,
    decide_group,
)


def _candidate(
    source: str,
    text: str,
    *,
    raw: str | None = None,
    conf: float = 0.80,
    bbox: tuple[float, float, float, float] = (100.0, 50.0, 160.0, 82.0),
    applied: bool = False,
    eligible: bool = True,
) -> Candidate:
    return Candidate(
        source=source,
        text_raw=raw or text,
        text_norm=text,
        bbox=bbox,
        confidence=conf,
        current_hybrid_applied=applied,
        eligible=eligible,
    )


def test_safe_paddle_addition_wins_without_easyocr_overlap() -> None:
    decision = decide_group(
        CandidateGroup(
            group_id="sample-001",
            candidates=[
                _candidate(
                    "paddle_addition",
                    "Cmaj7",
                    raw="Cmmj7",
                    conf=0.79,
                    applied=True,
                )
            ],
        )
    )

    assert decision["selected_text_norm"] == "Cmaj7"
    assert decision["selected_source"] == "paddle_addition"
    assert decision["status"] == "auto"


def test_same_root_paddle_candidate_replaces_suspicious_baseline() -> None:
    decision = decide_group(
        CandidateGroup(
            group_id="sample-001",
            candidates=[
                _candidate(
                    "easyocr_baseline",
                    "C19",
                    conf=0.61,
                    applied=True,
                ),
                _candidate(
                    "paddle_replacement_candidate",
                    "C7#9",
                    conf=0.99,
                ),
            ],
        )
    )

    assert decision["selected_text_norm"] == "C7#9"
    assert decision["selected_source"] == "paddle_replacement_candidate"
    assert decision["status"] == "auto"
    assert decision["reason"] == "same_root_paddle_candidate_for_suspicious_baseline"


def test_same_letter_accidental_candidate_can_replace_suspicious_baseline() -> None:
    decision = decide_group(
        CandidateGroup(
            group_id="sample-001",
            candidates=[
                _candidate(
                    "easyocr_baseline",
                    "A567",
                    conf=0.20,
                    applied=True,
                ),
                _candidate(
                    "paddle_replacement_candidate",
                    "Ab7",
                    conf=0.91,
                ),
            ],
        )
    )

    assert decision["selected_text_norm"] == "Ab7"
    assert decision["reason"] == "same_letter_accidental_paddle_candidate_for_suspicious_baseline"


def test_different_root_candidate_stays_review_not_auto_replace() -> None:
    decision = decide_group(
        CandidateGroup(
            group_id="sample-001",
            candidates=[
                _candidate(
                    "easyocr_baseline",
                    "C79",
                    conf=0.37,
                    applied=True,
                ),
                _candidate(
                    "paddle_replacement_candidate",
                    "Gmaj7",
                    conf=0.83,
                ),
            ],
        )
    )

    assert decision["selected_text_norm"] == "C79"
    assert decision["selected_source"] == "easyocr_baseline"
    assert decision["status"] == "review"


def test_plausible_baseline_with_same_root_candidate_stays_review() -> None:
    decision = decide_group(
        CandidateGroup(
            group_id="sample-001",
            candidates=[
                _candidate(
                    "easyocr_baseline",
                    "E9",
                    conf=0.40,
                    applied=True,
                ),
                _candidate(
                    "paddle_replacement_candidate",
                    "Esus4",
                    conf=0.89,
                ),
            ],
        )
    )

    assert decision["selected_text_norm"] == "E9"
    assert decision["status"] == "review"


def test_suppressed_only_group_is_ignored() -> None:
    decision = decide_group(
        CandidateGroup(
            group_id="sample-001",
            candidates=[
                _candidate(
                    "paddle_suppressed_addition",
                    "E-765",
                    conf=0.90,
                    eligible=False,
                )
            ],
        )
    )

    assert decision["selected_text_norm"] == "E-765"
    assert decision["status"] == "ignore"
    assert decision["reason"] == "no_eligible_candidate_in_group"
