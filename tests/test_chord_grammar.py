from pipeline.chords.grammar import looks_like_chord, looks_like_chord_ocr, normalize_text


def test_chord_grammar_accepts_common_printed_symbols() -> None:
    assert looks_like_chord("Dm7")
    assert looks_like_chord("G7")
    assert looks_like_chord("Cmaj7")
    assert looks_like_chord("B♭△")
    assert not looks_like_chord("Verse")


def test_chord_ocr_correction_and_normalization() -> None:
    accepted, corrected = looks_like_chord_ocr("97")

    assert accepted is True
    assert corrected == "G7"
    assert normalize_text("B♭△") == "Bbmaj7"
    assert normalize_text("F♯ø") == "F#m7b5"
