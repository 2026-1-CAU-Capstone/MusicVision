from __future__ import annotations

import re


_CHORD_RE = re.compile(
    r"""^
    (?P<root>[A-G])
    (?P<accidental>[#b♭♯]?)
    (?P<quality>
        maj|min|dim|aug|sus|add|△|m|M
    )?
    (?P<rest>[0-9()#b♭♯ø°+\-/△]*)
    (?:/ [A-G][#b♭♯]? )?
    $
    """,
    re.VERBOSE,
)


def looks_like_chord(text: str) -> bool:
    token = (text or "").strip()
    if not token:
        return False

    token = re.sub(r"\s*/\s*", "/", token)
    if len(token) > 16 or " " in token:
        return False

    return _CHORD_RE.match(token) is not None


_ROOT_FIXES: dict[str, str] = {
    "0": "G",
    "8": "B",
    "1": "I",
    "4": "D",
    "9": "G",
}

_BODY_FIXES: dict[str, str] = {
    "?": "7",
    '"': "7",
    "'": "7",
    "h": "b",
    "q": "b",
    "f": "#",
    "a": "△",
    "A": "△",
    "c": "#",
    "z": "7",
    "Z": "7",
}

_ROOT_ACCIDENTAL_FIXES: dict[str, str] = {
    "h": "b",
    "q": "b",
    "n": "b",
    "o": "b",
    "f": "#",
    "c": "#",
}


def _ocr_correct(text: str) -> str:
    if not text:
        return text

    text = re.sub(r"\s*/\s*", "/", text)
    text = text.rstrip(".,;:!|")
    text = re.sub(r"inaj", "maj", text, flags=re.IGNORECASE)
    chars = list(text)

    if chars[0].isalpha():
        chars[0] = chars[0].upper()

    root_end = 1
    if len(chars) > 1 and chars[1] in ("#", "b", "♭", "♯"):
        root_end = 2
    elif len(chars) > 1 and chars[1] in _ROOT_ACCIDENTAL_FIXES:
        chars[1] = _ROOT_ACCIDENTAL_FIXES[chars[1]]
        root_end = 2

    if chars[0] in _ROOT_FIXES:
        chars[0] = _ROOT_FIXES[chars[0]]

    for index in range(root_end, len(chars)):
        char = chars[index]
        if char in ("a", "A") and index == len(chars) - 1:
            chars[index] = "△"
        elif char in ("s", "S") and index > root_end and chars[index - 1] == "b":
            chars[index] = "5"
        elif char in _BODY_FIXES and char not in ("a", "A"):
            chars[index] = _BODY_FIXES[char]

    result = "".join(chars)
    result = re.sub(r"mn7$", "m7", result)
    slash_match = re.search(r"/([a-gA-G0-9])", result)
    if slash_match:
        bass_char = slash_match.group(1)
        if bass_char.isalpha():
            bass_fixed = bass_char.upper()
        else:
            bass_fixed = _ROOT_FIXES.get(bass_char, bass_char)
        result = result[: slash_match.start(1)] + bass_fixed + result[slash_match.end(1) :]

    return result


def looks_like_chord_ocr(text: str) -> tuple[bool, str]:
    corrected = _ocr_correct((text or "").strip())
    return looks_like_chord(corrected), corrected


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""

    token = text.strip()
    token = token.replace("♭", "b").replace("♯", "#")
    token = token.replace("△", "maj7")
    token = token.replace("°", "dim")
    token = token.replace("ø", "m7b5")

    private_map = {
        "\ue260": "b",
        "\ue262": "#",
        "\ue10d": "b",
        "\ue10c": "#",
    }
    for source, replacement in private_map.items():
        token = token.replace(source, replacement)

    return token.replace("–", "-")
