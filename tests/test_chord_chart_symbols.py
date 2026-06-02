from pipeline.chord_charts.chord_symbol import parse_chord_symbol


def _norm(text: str) -> str:
    parsed = parse_chord_symbol(text)
    assert parsed is not None
    return parsed.text_norm


def test_chart_chord_symbols_accept_everyday_linear_notation() -> None:
    assert _norm("Abm7b5") == "Abm7b5"
    assert _norm("Abmin7b5") == "Abm7b5"
    assert _norm("Ab-7b5") == "Abm7b5"
    assert _norm("Abm7(b5)") == "Abm7(b5)"


def test_chart_chord_symbols_normalize_chart_glyph_notation() -> None:
    assert _norm("A\u00f87") == "Am7b5"
    assert _norm("Bb\u25b37") == "Bbmaj7"
    assert _norm("Eb-\u25b37") == "EbmMaj7"
    assert _norm("F\u266f7#5") == "F#7#5"
    assert _norm("Bb6/F") == "Bb6/F"


def test_chart_chord_symbols_repair_common_chart_ocr_spellings() -> None:
    assert _norm("IC-7") == "Cm7"
    assert _norm("Fz") == "F7"
    assert _norm("Fz5") == "F7#5"
    assert _norm("D7v13") == "D7b13"
    assert _norm("G719") == "G7b9"
    assert _norm("Baz") == "Bbmaj7"
    assert _norm("Aoz") == "Am7b5"
    assert _norm("Bhz") == "Bb7"
    assert _norm("6z") == "G7"
    assert _norm("F7;5") == "F7#5"
    assert _norm("0D113") == "D7b13"
    assert _norm("Gc") == "Gmaj7"
