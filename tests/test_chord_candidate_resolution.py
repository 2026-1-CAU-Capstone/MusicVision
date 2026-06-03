from __future__ import annotations

from pipeline.chords.candidate_resolution import resolve_chord_ocr_text
from pipeline.chords.grammar import looks_like_chord_ocr


def test_structural_ocr_corrections_accept_spacing_minor_and_g_root() -> None:
    assert looks_like_chord_ocr("C 7") == (True, "C7")
    assert looks_like_chord_ocr("Bb maj7") == (True, "Bbmaj7")
    assert looks_like_chord_ocr("C_7") == (True, "C-7")
    assert looks_like_chord_ocr("6m7") == (True, "Gm7")
    assert looks_like_chord_ocr("CM7") == (True, "Cmaj7")


def test_candidate_resolution_fixes_observed_major_seventh_misreads() -> None:
    examples = {
        "Cm4it": "Cmaj7",
        "Fm4T": "Fmaj7",
        "Cm4t": "Cmaj7",
        "Fmajt": "Fmaj7",
        "Bbmai7": "Bbmaj7",
        "Fm4i7": "Fmaj7",
        "Cm4jt": "Cmaj7",
    }

    for raw_text, expected in examples.items():
        resolution = resolve_chord_ocr_text(raw_text)

        assert resolution.accepted is True
        assert resolution.auto_corrected is True
        assert resolution.text_norm == expected


def test_candidate_resolution_rejects_fragments_without_roots() -> None:
    for raw_text in ("maj", "sus"):
        resolution = resolve_chord_ocr_text(raw_text)

        assert resolution.accepted is False
        assert resolution.suggestions == []


def test_candidate_resolution_marks_uncertain_near_chords_without_accepting() -> None:
    resolution = resolve_chord_ocr_text("Cx7")

    assert resolution.accepted is False
    assert resolution.reject_context() == {
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
