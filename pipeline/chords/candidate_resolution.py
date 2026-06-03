from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pipeline.chords.grammar import looks_like_chord, looks_like_chord_ocr, normalize_text


AUTO_CORRECT_MIN_SCORE = 0.75
AUTO_CORRECT_MIN_MARGIN = 0.05
SUGGESTION_MIN_SCORE = 0.58
SUSPICIOUS_REPAIR_MIN_SCORE = 0.86

_ROOTS = tuple("ABCDEFG")
_ACCIDENTALS = ("", "b", "#")
_COMMON_SUFFIXES = (
    "",
    "5",
    "6",
    "7",
    "9",
    "11",
    "13",
    "m",
    "m6",
    "m7",
    "m9",
    "m11",
    "m13",
    "-",
    "-6",
    "-7",
    "-9",
    "-11",
    "-13",
    "maj",
    "maj6",
    "maj7",
    "maj9",
    "maj13",
    "dim",
    "dim7",
    "aug",
    "+",
    "+7",
    "sus",
    "sus2",
    "sus4",
    "7sus",
    "7sus4",
    "9sus",
    "9sus4",
    "add9",
    "6/9",
    "m7b5",
    "7b5",
    "7#5",
    "7b9",
    "7#9",
    "13b9",
    "alt",
)

_CONFUSION_GROUPS = (
    frozenset(("7", "t", "z", "?", '"', "'")),
    frozenset(("a", "4", "r")),
    frozenset(("i", "j", "1", "l")),
    frozenset(("g", "6", "9")),
    frozenset(("b", "8", "h", "q")),
    frozenset(("s", "5")),
    frozenset(("#", "f", "c")),
)
_LOW_INSERTION_CHARS = frozenset("ij")
_LOW_DELETION_CHARS = frozenset("ij")


@dataclass(frozen=True)
class ChordOCRResolution:
    accepted: bool
    text_norm: str
    corrected_text: str
    suggestions: list[dict[str, Any]]
    auto_corrected: bool = False

    def reject_context(self) -> dict[str, Any]:
        if not self.suggestions:
            return {}
        return {
            "candidate_kind": "uncertain_chord",
            "suggestions": self.suggestions,
        }

    def uncertain_context(self) -> dict[str, Any]:
        if self.suggestions:
            return self.reject_context()
        if not self.accepted or not self.text_norm:
            return {}
        return {
            "candidate_kind": "uncertain_chord",
            "suggestions": [
                {
                    "text_norm": self.text_norm,
                    "score": 1.0,
                    "reason": "valid_chord_but_low_ocr_confidence",
                }
            ],
        }


def resolve_chord_ocr_text(text: str) -> ChordOCRResolution:
    passed, corrected = looks_like_chord_ocr(text)
    if passed:
        text_norm = normalize_text(corrected)
        if _is_suspicious_accepted_chord(text_norm):
            suggestions = suggest_suspicious_accepted_chord_candidates(
                raw_text=text,
                accepted_text=text_norm,
            )
            if _has_clear_auto_correction(suggestions):
                best = suggestions[0]
                if str(best["text_norm"]) != text_norm:
                    return ChordOCRResolution(
                        accepted=True,
                        text_norm=str(best["text_norm"]),
                        corrected_text=str(best["text_norm"]),
                        suggestions=suggestions,
                        auto_corrected=True,
                    )

        return ChordOCRResolution(
            accepted=True,
            text_norm=text_norm,
            corrected_text=corrected,
            suggestions=[],
            auto_corrected=False,
        )

    suggestions = suggest_chord_ocr_candidates(text)
    if _has_clear_auto_correction(suggestions):
        best = suggestions[0]
        return ChordOCRResolution(
            accepted=True,
            text_norm=str(best["text_norm"]),
            corrected_text=str(best["text_norm"]),
            suggestions=suggestions,
            auto_corrected=True,
        )

    return ChordOCRResolution(
        accepted=False,
        text_norm=normalize_text(corrected),
        corrected_text=corrected,
        suggestions=suggestions,
        auto_corrected=False,
    )


def suggest_suspicious_accepted_chord_candidates(
    *,
    raw_text: str,
    accepted_text: str,
    max_suggestions: int = 3,
) -> list[dict[str, Any]]:
    variants = _repair_variant_texts(raw_text)
    suggestions: list[tuple[float, str]] = []
    seen = {accepted_text}

    for variant, edit_count in variants:
        if not looks_like_chord(variant):
            continue
        variant_norm = normalize_text(variant)
        if variant_norm in seen:
            continue
        if not _is_common_chord_symbol(variant_norm):
            continue
        seen.add(variant_norm)
        score = max(
            SUSPICIOUS_REPAIR_MIN_SCORE,
            round(1.0 - (0.05 * edit_count), 3),
        )
        suggestions.append((score, variant_norm))

    suggestions.extend(
        (
            float(suggestion["score"]),
            str(suggestion["text_norm"]),
        )
        for suggestion in suggest_chord_ocr_candidates(raw_text)
        if str(suggestion["text_norm"]) not in seen
    )
    suggestions.sort(key=lambda item: (-item[0], len(item[1]), item[1]))

    result = []
    emitted = set()
    for score, candidate in suggestions:
        if candidate in emitted:
            continue
        emitted.add(candidate)
        result.append(
            {
                "text_norm": candidate,
                "score": round(score, 3),
                "reason": "suspicious_accepted_chord_repair",
            }
        )
        if len(result) >= max_suggestions:
            break

    return result


def suggest_chord_ocr_candidates(
    text: str,
    *,
    max_suggestions: int = 3,
) -> list[dict[str, Any]]:
    _passed, corrected = looks_like_chord_ocr(text)
    compare_text = _comparison_text(corrected)
    if len(compare_text) < 2:
        return []

    roots = _candidate_roots(corrected)
    if not roots:
        return []

    scored: list[tuple[float, str]] = []
    for candidate in _candidate_symbols_for_roots(tuple(roots)):
        score = _similarity_score(compare_text, _comparison_text(candidate))
        if score >= SUGGESTION_MIN_SCORE:
            scored.append((score, candidate))

    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    result = []
    seen = set()
    for score, candidate in scored:
        candidate_norm = normalize_text(candidate)
        if candidate_norm in seen:
            continue
        seen.add(candidate_norm)
        result.append(
            {
                "text_norm": candidate_norm,
                "score": round(score, 3),
                "reason": "near_valid_chord_candidate",
            }
        )
        if len(result) >= max_suggestions:
            break

    return result


def _has_clear_auto_correction(suggestions: list[dict[str, Any]]) -> bool:
    if not suggestions:
        return False

    best_score = float(suggestions[0]["score"])
    if best_score < AUTO_CORRECT_MIN_SCORE:
        return False

    if len(suggestions) == 1:
        return True

    second_score = float(suggestions[1]["score"])
    return best_score - second_score >= AUTO_CORRECT_MIN_MARGIN


def _is_suspicious_accepted_chord(text: str) -> bool:
    token = normalize_text(text).strip()
    if not token:
        return False
    if token.count("(") != token.count(")"):
        return True
    if _is_common_chord_symbol(token):
        return False
    return True


def _is_common_chord_symbol(text: str) -> bool:
    token = normalize_text(text).strip()
    roots = _candidate_roots(token)
    if not roots:
        return False
    return token in _candidate_symbols_for_roots(tuple(roots))


def _candidate_roots(text: str) -> list[str]:
    token = normalize_text(text).strip()
    if not token:
        return []

    root = token[0].upper()
    if root not in _ROOTS:
        return []

    accidental = ""
    if len(token) > 1 and token[1] in ("b", "#"):
        accidental = token[1]

    return [f"{root}{accidental}"]


def _repair_variant_texts(text: str) -> list[tuple[str, int]]:
    _passed, corrected = looks_like_chord_ocr(text)
    compact = _comparison_preserving_symbols(corrected)
    if len(compact) < 2:
        return []

    option_sets: list[list[tuple[str, int]]] = []
    for index, char in enumerate(compact):
        options = [(char, 0)]
        if index == 1 and char in {"5", "6"}:
            options.append(("b", 1))
        if index == 1 and char == "8":
            options.append(("#", 1))
        if char == "1" and _looks_like_terminal_seven(compact, index):
            options.append(("7", 1))
        if char == "2" and _looks_like_minor_dash(compact, index):
            options.append(("-", 1))
        if char == "9" and index + 1 < len(compact) and compact[index + 1] == ")":
            options.append(("7", 1))
        if char == ")" and "(" not in compact[: index + 1]:
            options.append(("", 1))
        option_sets.append(options)

    variants: dict[str, int] = {}

    def emit(index: int, chars: list[str], edits: int) -> None:
        if len(variants) > 96:
            return
        if index == len(option_sets):
            candidate = "".join(chars)
            if candidate and candidate != compact:
                variants[candidate] = min(edits, variants.get(candidate, edits))
            return
        for replacement, edit_cost in option_sets[index]:
            if replacement:
                chars.append(replacement)
            emit(index + 1, chars, edits + edit_cost)
            if replacement:
                chars.pop()

    emit(0, [], 0)
    return sorted(variants.items(), key=lambda item: (item[1], item[0]))


def _looks_like_terminal_seven(text: str, index: int) -> bool:
    previous = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    if next_char in {"", ")"}:
        return True
    if previous in {"-", "+", "#", "b"} and next_char in {"", ")"}:
        return True
    return False


def _looks_like_minor_dash(text: str, index: int) -> bool:
    previous = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    return previous in {"b", "#", "5", "6", "8"} and next_char in {"1", "7"}


@lru_cache(maxsize=32)
def _candidate_symbols_for_roots(roots: tuple[str, ...]) -> tuple[str, ...]:
    candidates = []
    for root in roots:
        for suffix in _COMMON_SUFFIXES:
            candidate = f"{root}{suffix}"
            if looks_like_chord(candidate):
                candidates.append(candidate)
    return tuple(candidates)


def _comparison_text(text: str) -> str:
    token = normalize_text(text).strip().lower()
    return "".join(char for char in token if not char.isspace())


def _comparison_preserving_symbols(text: str) -> str:
    token = normalize_text(text).strip()
    return "".join(char for char in token if not char.isspace())


def _similarity_score(source: str, candidate: str) -> float:
    if not source or not candidate:
        return 0.0
    cost = _weighted_edit_distance(source, candidate)
    return max(0.0, 1.0 - (cost / max(len(source), len(candidate))))


def _weighted_edit_distance(source: str, candidate: str) -> float:
    previous = [0.0]
    for char in candidate:
        previous.append(previous[-1] + _insertion_cost(char))

    for source_index, source_char in enumerate(source, start=1):
        current = [previous[0] + _deletion_cost(source_char)]
        for candidate_index, candidate_char in enumerate(candidate, start=1):
            substitute = previous[candidate_index - 1] + _substitution_cost(
                source_char,
                candidate_char,
            )
            delete = previous[candidate_index] + _deletion_cost(source_char)
            insert = current[candidate_index - 1] + _insertion_cost(candidate_char)
            current.append(min(substitute, delete, insert))
        previous = current

    return previous[-1]


def _substitution_cost(source: str, candidate: str) -> float:
    if source == candidate:
        return 0.0
    for group in _CONFUSION_GROUPS:
        if source in group and candidate in group:
            return 0.22
    return 1.0


def _insertion_cost(char: str) -> float:
    return 0.45 if char in _LOW_INSERTION_CHARS else 0.80


def _deletion_cost(char: str) -> float:
    return 0.45 if char in _LOW_DELETION_CHARS else 0.80
