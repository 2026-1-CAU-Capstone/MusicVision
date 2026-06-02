from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ROOT_RE = re.compile(r"^(?P<root>[A-Ga-g])(?P<accidental>[#b]?)")
ALTERATION_RE = re.compile(r"[#b](?:5|9|11|13)")
EXTENSION_RE = re.compile(r"(?<![#b])(?:6|7|9|11|13)")


@dataclass(frozen=True)
class ParsedChord:
    text_raw: str
    text_norm: str
    text_display: str
    root: str
    accidental: str | None
    quality: str | None
    extensions: list[str]
    alterations: list[str]
    bass: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_raw": self.text_raw,
            "text_norm": self.text_norm,
            "text_display": self.text_display,
            "components": {
                "root": self.root,
                "accidental": self.accidental,
                "quality": self.quality,
                "extensions": self.extensions,
                "alterations": self.alterations,
                "bass": self.bass,
            },
        }


def parse_chord_symbol(text: str | None) -> ParsedChord | None:
    raw = (text or "").strip()
    if not raw:
        return None

    compact = _compact_symbol(raw)
    if len(compact) > 24:
        return None

    main, bass = _split_slash_bass(compact)
    bass_norm = _normalize_root_token(bass) if bass else None
    if bass is not None and bass_norm is None:
        return None

    match = ROOT_RE.match(main)
    if match is None:
        return None

    root = match.group("root").upper()
    accidental = match.group("accidental") or None
    body = main[match.end() :]
    canonical_body = _canonical_body(body)
    if canonical_body is None:
        return None

    text_norm = f"{root}{accidental or ''}{canonical_body}"
    if bass_norm is not None:
        text_norm = f"{text_norm}/{bass_norm}"

    if not _looks_like_canonical_body(canonical_body):
        return None

    return ParsedChord(
        text_raw=raw,
        text_norm=text_norm,
        text_display=raw,
        root=root,
        accidental=accidental,
        quality=_quality_from_body(canonical_body),
        extensions=EXTENSION_RE.findall(canonical_body),
        alterations=ALTERATION_RE.findall(canonical_body),
        bass=bass_norm,
    )


def looks_like_chord_symbol(text: str | None) -> bool:
    return parse_chord_symbol(text) is not None


def _compact_symbol(text: str) -> str:
    token = text.strip()
    sequence_replacements = {
        "\u00f87": "m7b5",
        "\u25b37": "maj7",
        "\u22067": "maj7",
        "\u03947": "maj7",
    }
    for source, replacement in sequence_replacements.items():
        token = token.replace(source, replacement)

    replacements = {
        "\u266d": "b",
        "\ue260": "b",
        "\ue10d": "b",
        "\u266f": "#",
        "\ue262": "#",
        "\ue10c": "#",
        "\u25b3": "maj7",
        "\u2206": "maj7",
        "\u0394": "maj7",
        "\u00f8": "m7b5",
        "\u00b0": "dim",
        "\u2212": "-",
        "\u2013": "-",
        "\u2014": "-",
    }
    for source, replacement in replacements.items():
        token = token.replace(source, replacement)

    token = re.sub(r"\s*/\s*", "/", token)
    token = re.sub(r"\s+", "", token)
    token = token.strip(".,;:!|")
    return _repair_ocr_spellings(token)


def _repair_ocr_spellings(token: str) -> str:
    token = re.sub(r"^[|Il\[]+(?=[A-Ga-g])", "", token)
    token = token.replace(";", "#")
    token = token.replace("v", "b").replace("V", "b")
    token = re.sub(r"^[0O](?=[Dd])", "", token)
    if re.fullmatch(r"N[-\u2212\u2013\u2014mM]?[0-9#b()+-]*", token):
        token = f"A{token[1:]}"
    special_repairs = {
        "0713": "D7b13",
        "0D7h3": "D7b13",
        "0D113": "D7b13",
        "D113": "D7b13",
        "6719": "G7b9",
        "6z": "G7",
        "9z": "G7",
    }
    if token in special_repairs:
        return special_repairs[token]

    root_repairs = {
        "6": "G",
        "9": "G",
        "8": "B",
    }
    if len(token) > 1 and token[0] in root_repairs:
        token = f"{root_repairs[token[0]]}{token[1:]}"

    match = ROOT_RE.match(token)
    if match is None:
        return token

    root = match.group("root").upper()
    accidental = match.group("accidental")
    rest = token[match.end() :]
    rest_lower = rest.lower()
    prefix = f"{root}{accidental}"

    if accidental and rest_lower in {"z", "az", "a7", "lz", "l7"}:
        return f"{prefix}maj7"
    if not accidental and root == "B" and rest_lower in {"zz", "4z"}:
        return "Bbmaj7"
    if not accidental and rest_lower in {"az", "a7", "lz", "l7"}:
        return f"{prefix if accidental else root + 'b'}maj7"
    if root == "A" and not accidental and rest_lower in {"zz", "oz"}:
        return "Am7b5"
    if root == "E" and not accidental and rest_lower == "oz":
        return "Edim7"
    if root == "B" and not accidental and rest_lower == "s":
        return "Bb6"
    if not accidental and rest_lower in {"hz", "qz", "nz", "pz"}:
        return f"{root}bmaj7"
    if not accidental and rest_lower in {"h", "q", "n", "p"}:
        return f"{root}b"
    if not accidental and rest_lower.startswith(("h", "q", "n", "p")):
        repaired_tail = rest[1:].replace("z", "7").replace("Z", "7")
        return f"{root}b{repaired_tail}"
    if root in {"A", "B"} and not accidental and rest_lower == "z":
        return f"{root}b7"
    if rest_lower in {"7s", "75", "z5"}:
        return f"{prefix}7#5"
    if rest_lower in {"c", "c7"}:
        return f"{prefix}maj7"
    if root == "A" and not accidental and rest_lower == "d7":
        return "Am7b5"
    if rest_lower == "719":
        return f"{prefix}7b9"
    if rest_lower in {"7b1z", "7h3", "713"}:
        return f"{prefix}7b13"

    repaired_rest = rest.replace("z", "7").replace("Z", "7")
    repaired_rest = re.sub(r"7b1[37]", "7b13", repaired_rest)
    return f"{prefix}{repaired_rest}"


def _split_slash_bass(token: str) -> tuple[str, str | None]:
    if "/" not in token:
        return token, None

    main, bass = token.rsplit("/", 1)
    if not main or not bass:
        return token, None

    return main, bass


def _normalize_root_token(token: str) -> str | None:
    compact = _compact_symbol(token)
    match = ROOT_RE.match(compact)
    if match is None or match.end() != len(compact):
        return None

    return f"{match.group('root').upper()}{match.group('accidental')}"


def _canonical_body(body: str) -> str | None:
    if not body:
        return ""

    original = body
    lower = body.lower()

    if lower.startswith("min"):
        body = "m" + body[3:]
        lower = body.lower()
    elif lower.startswith("-"):
        body = "m" + body[1:]
        lower = body.lower()
    elif lower.startswith("m") and not lower.startswith("maj"):
        body = "m" + body[1:]
        lower = body.lower()
    elif lower.startswith("maj"):
        body = "maj" + body[3:]
        lower = body.lower()
    elif body.startswith("M"):
        body = "maj" + body[1:]
        lower = body.lower()
    elif lower.startswith(("o", "0")):
        body = "dim" + body[1:]
        lower = body.lower()

    if lower.startswith("mmaj"):
        suffix = body[4:] or "7"
        body = f"mMaj{suffix}"
    elif lower == "mmaj7":
        body = "mMaj7"
    elif lower == "maj":
        body = "maj7"
    elif lower == "m7b5":
        body = "m7b5"
    elif lower.startswith("sus"):
        body = "sus" + body[3:]
    elif lower.startswith("add"):
        body = "add" + body[3:]

    letters_without_accidentals = re.sub(r"[b#]", "", body)
    if body == original and re.search(r"[A-Za-z]", letters_without_accidentals):
        allowed = ("m", "maj", "mMaj", "dim", "aug", "sus", "add", "alt")
        if not body.startswith(allowed):
            return None

    return body


def _looks_like_canonical_body(body: str) -> bool:
    if not body:
        return True

    return (
        re.fullmatch(
            r"(?:mMaj|maj|m|dim|aug|sus|add|alt)?[0-9#b()+-]*",
            body,
        )
        is not None
    )


def _quality_from_body(body: str) -> str | None:
    if not body:
        return "major"
    if body.startswith("mMaj"):
        return "minor_major"
    if body.startswith("m7b5"):
        return "half_diminished"
    if body.startswith("maj"):
        return "major"
    if body.startswith("m"):
        return "minor"
    if body.startswith("dim"):
        return "diminished"
    if body.startswith("aug"):
        return "augmented"
    if body.startswith("sus"):
        return "suspended"
    if body.startswith("add"):
        return "added_tone"
    if body.startswith("alt"):
        return "altered"
    if body[0].isdigit():
        return "dominant"
    return None
