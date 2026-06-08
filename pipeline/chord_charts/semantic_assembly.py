from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from pipeline.chord_charts.chord_symbol import (
    ParsedChord,
    parse_chord_symbol,
    repair_numeric_flat_suffix,
)
from pipeline.chord_charts.ocr_backend import OCRToken
from pipeline.chord_charts.visual_suffix import (
    normalize_suffix_ocr_text,
    suffix_has_triangle as visual_suffix_has_triangle,
)

ROOT_REGION_NAMES = {"root"}
ACCIDENTAL_REGION_NAMES = {"root_accidental"}
SUFFIX_REGION_NAMES = {"suffix_lower_right"}


@dataclass(frozen=True)
class SemanticAssemblyResult:
    tokens: list[OCRToken]
    diagnostics: list[dict[str, Any]]


@dataclass(frozen=True)
class _RootCandidate:
    token: OCRToken
    root: str
    accidental: str | None
    body: str


def assemble_semantic_chord_tokens(
    tokens: list[OCRToken],
    *,
    image: np.ndarray | None = None,
    skip_measure_indices: set[int] | None = None,
    source: str = "cell_ocr_semantic_assembled",
) -> SemanticAssemblyResult:
    skip_measure_indices = skip_measure_indices or set()
    grouped: dict[int, list[OCRToken]] = defaultdict(list)
    for token in tokens:
        if token.measure_index is not None:
            grouped[token.measure_index].append(token)

    assembled_tokens: list[OCRToken] = []
    diagnostics: list[dict[str, Any]] = []
    for measure_index, measure_tokens in sorted(grouped.items()):
        if measure_index in skip_measure_indices:
            diagnostics.append(
                {
                    "measure_index": measure_index,
                    "status": "skipped",
                    "reason": "repeat_symbol_priority",
                    "fragments": [token.to_dict() for token in measure_tokens],
                }
            )
            continue

        measure_width = _measure_width(measure_tokens)
        roots = _deduplicate_root_candidates(
            [
                candidate
                for candidate in (
                    _root_candidate(token)
                    for token in measure_tokens
                    if token.region in ROOT_REGION_NAMES
                )
                if candidate is not None
            ],
            measure_width=measure_width,
        )
        if not roots:
            continue

        for index, root in enumerate(roots):
            next_root_x = roots[index + 1].token.cx if index + 1 < len(roots) else None
            suffix_candidates = [
                token
                for token in measure_tokens
                if token.region in SUFFIX_REGION_NAMES
            ]
            accidental_token = _nearest_related_token(
                root.token,
                [
                    token
                    for token in measure_tokens
                    if token.region in ACCIDENTAL_REGION_NAMES
                    and _accidental_from_token(token.text) is not None
                ],
                max_distance=max(40.0, measure_width * 0.18),
                next_root_x=next_root_x,
            )
            suffix_tokens = _related_tokens(
                root.token,
                [
                    token
                    for token in suffix_candidates
                    if _body_from_suffix_token(
                        token,
                        image=image,
                        root=root,
                        accidental_token=accidental_token,
                    )
                    is not None
                ],
                max_distance=max(95.0, measure_width * 0.48),
                next_root_x=next_root_x,
            )
            accidental = root.accidental
            if accidental is None and accidental_token is not None:
                accidental = _accidental_from_token(accidental_token.text)

            suffix_body = _combine_suffix_token_bodies(
                suffix_tokens,
                image=image,
                root=root,
                accidental_token=accidental_token,
            )
            if suffix_body is None and _has_related_invalid_suffix(
                root.token,
                suffix_candidates,
                max_distance=max(95.0, measure_width * 0.48),
                next_root_x=next_root_x,
                image=image,
                root=root,
                accidental_token=accidental_token,
            ):
                diagnostics.append(
                    _diagnostic(
                        measure_index=measure_index,
                        status="rejected",
                        text=f"{root.root}{accidental or ''}",
                        root=root,
                        accidental_token=accidental_token,
                        suffix_tokens=[],
                        reason="nearby suffix OCR was invalid",
                    )
                )
                continue

            body = _merge_bodies(root.body, suffix_body)
            text = f"{root.root}{accidental or ''}{body}"
            parsed = parse_chord_symbol(text)
            if parsed is None:
                diagnostics.append(
                    _diagnostic(
                        measure_index=measure_index,
                        status="rejected",
                        text=text,
                        root=root,
                        accidental_token=accidental_token,
                        suffix_tokens=suffix_tokens,
                        reason="assembled text failed chord grammar",
                    )
                )
                continue

            used_tokens = [root.token]
            if accidental_token is not None:
                used_tokens.append(accidental_token)
            used_tokens.extend(suffix_tokens)
            assembled_token = OCRToken(
                text=parsed.text_norm,
                bbox=_union_bbox([token.bbox for token in used_tokens]),
                confidence=_combined_confidence(used_tokens),
                source=source,
                row_index=root.token.row_index,
                col_index=root.token.col_index,
                measure_index=measure_index,
                region="semantic_chord",
            )
            assembled_tokens.append(assembled_token)
            diagnostics.append(
                _diagnostic(
                    measure_index=measure_index,
                    status="accepted",
                    text=parsed.text_norm,
                    root=root,
                    accidental_token=accidental_token,
                    suffix_tokens=suffix_tokens,
                    reason=None,
                )
            )

    assembled_tokens.sort(
        key=lambda token: (
            token.measure_index or 0,
            token.bbox[0],
            token.bbox[1],
        )
    )
    return SemanticAssemblyResult(tokens=assembled_tokens, diagnostics=diagnostics)


def _root_candidate(token: OCRToken) -> _RootCandidate | None:
    letter_match = re.search(r"[A-Ga-g]", token.text or "")
    if letter_match is not None:
        return _RootCandidate(
            token=token,
            root=letter_match.group(0).upper(),
            accidental=None,
            body="",
        )

    parsed = parse_chord_symbol(token.text)
    if parsed is None:
        return None

    return _RootCandidate(
        token=token,
        root=parsed.root,
        accidental=parsed.accidental,
        body="",
    )


def _deduplicate_root_candidates(
    roots: list[_RootCandidate],
    *,
    measure_width: float,
) -> list[_RootCandidate]:
    if len(roots) < 2:
        return sorted(roots, key=lambda candidate: candidate.token.cx)

    threshold = max(42.0, measure_width * 0.12)
    groups: list[list[_RootCandidate]] = []
    for root in sorted(roots, key=lambda candidate: candidate.token.cx):
        if not groups or abs(root.token.cx - _root_group_center(groups[-1])) > threshold:
            groups.append([root])
        else:
            groups[-1].append(root)

    return [
        max(group, key=_root_candidate_score)
        for group in groups
    ]


def _root_group_center(group: list[_RootCandidate]) -> float:
    return float(np.mean([root.token.cx for root in group]))


def _root_candidate_score(root: _RootCandidate) -> float:
    confidence = float(root.token.confidence or 0.0)
    score = confidence * 3.0
    if root.token.region == "root":
        score += 1.5
    if len(re.sub(r"\s+", "", root.token.text or "")) == 1:
        score += 0.3
    return score


def _body_from_parsed(parsed: ParsedChord) -> str:
    main = parsed.text_norm.split("/", 1)[0]
    prefix = f"{parsed.root}{parsed.accidental or ''}"
    if main.startswith(prefix):
        return main[len(prefix) :]
    return ""


def _accidental_from_token(text: str | None) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return None
    has_sharp = any(char in compact for char in "#\u266f\ue262\ue10c")
    has_flat = any(char in compact for char in "bBvVhHpPnN6\u266d\ue260\ue10d")
    if has_sharp and has_flat:
        return "b"
    if has_sharp:
        return "#"
    if has_flat:
        return "b"
    return None


def _body_from_suffix_text(text: str | None) -> str | None:
    compact = re.sub(r"\s+", "", text or "").strip(".,;:!|[](){}")
    if not compact:
        return None
    if compact in {"b", "B", "#", "\u266d", "\u266f"}:
        return None
    if compact in {"\u00f8", "\u00f87"}:
        return "m7b5"
    if compact in {"\u00b0", "o", "O", "0"}:
        return "dim"
    if compact in {"\u00b07", "o7", "O7", "07"}:
        return "dim7"
    if compact in {"\u25b3", "\u2206", "\u0394", "\u25b37", "\u22067", "\u03947"}:
        return "maj7"
    if compact in {"77", "777"}:
        return "7"

    numeric_flat = repair_numeric_flat_suffix(compact)
    if numeric_flat is not None:
        return numeric_flat

    numeric_flat_nine = _repair_numeric_flat_nine_suffix(compact)
    if numeric_flat_nine is not None:
        return numeric_flat_nine

    numeric_sharp = _repair_numeric_sharp_suffix(compact)
    if numeric_sharp is not None:
        return numeric_sharp

    numeric_flat_thirteen = _repair_numeric_flat_thirteen_suffix(compact)
    if numeric_flat_thirteen is not None:
        return numeric_flat_thirteen

    if compact.isdigit() and compact not in {"6", "7", "9", "11", "13"}:
        return None

    parsed = parse_chord_symbol(compact)
    if parsed is not None:
        return _body_from_parsed(parsed)

    compact = compact.replace("\u25b3", "maj7")
    compact = compact.replace("\u2206", "maj7")
    compact = compact.replace("\u0394", "maj7")
    compact = compact.replace("\u00f8", "m7b5")
    compact = compact.replace("\u00b0", "dim")
    compact = compact.replace("\u2212", "-")
    compact = compact.replace("\u2013", "-")
    compact = compact.replace("\u2014", "-")
    compact = compact.replace(";", "#")
    compact = compact.replace("z", "7").replace("Z", "7")
    compact = compact.replace("v", "b").replace("V", "b")

    if compact.startswith("-"):
        compact = f"m{compact[1:]}"
    lower = compact.lower()
    if lower.startswith("min"):
        compact = f"m{compact[3:]}"
    elif compact.startswith("M"):
        compact = f"maj{compact[1:]}"

    if re.fullmatch(r"(?:mMaj|maj|m|dim|aug|sus|add|alt)?[0-9#b()+-]*", compact):
        return compact
    return None


def _repair_numeric_sharp_suffix(text: str) -> str | None:
    match = re.fullmatch(r"74(5|9|11|13)", text)
    if match is None:
        return None
    return f"7#{match.group(1)}"


def _repair_numeric_flat_nine_suffix(text: str) -> str | None:
    if text not in {"719", "7l9", "7I9"}:
        return None
    return "7b9"


def _repair_numeric_flat_thirteen_suffix(text: str) -> str | None:
    if text in {"713", "7l3", "7I3", "7113", "7l13", "7I13"}:
        return "7b13"
    if re.fullmatch(r"[3)]?7(?:6|b|B)13", text):
        return "7b13"
    if text == "3711":
        return "7b13"
    return None


def _body_from_suffix_token(
    token: OCRToken,
    *,
    image: np.ndarray | None,
    root: _RootCandidate | None = None,
    accidental_token: OCRToken | None = None,
) -> str | None:
    compact = re.sub(r"\s+", "", token.text or "").strip(".,;:!|[](){}")
    if _wide_suffix_accidental_prefix_is_context(compact, token, accidental_token):
        return "7"

    if image is not None:
        visual_text = normalize_suffix_ocr_text(
            token.text or "",
            _token_image_crop(token, image, pad=8),
        )
        if visual_text != (token.text or ""):
            visual_body = _body_from_suffix_text(visual_text)
            if visual_body is not None:
                return visual_body

    if (
        image is not None
        and _suffix_text_can_be_triangle(compact)
        and _suffix_has_triangle(token, image)
    ):
        return "maj7"

    if compact in {"77", "777", "76", "776"}:
        if image is not None and _suffix_has_minor_dash(token, image):
            return f"m{compact[-1]}"
        if compact in {"76", "776"}:
            return None
        return "7"

    return _body_from_suffix_text(token.text)


def _wide_suffix_accidental_prefix_is_context(
    compact: str,
    token: OCRToken,
    accidental_token: OCRToken | None,
) -> bool:
    if token.region != "suffix_wide" or accidental_token is None:
        return False
    if _accidental_from_token(accidental_token.text) is None:
        return False
    return compact in {
        "07",
        "0z",
        "0Z",
        "O7",
        "Oz",
        "o7",
        "oz",
        "67",
        "6z",
        "6Z",
        "b7",
        "B7",
    }


def _suffix_text_can_be_triangle(compact: str) -> bool:
    if any(char in compact for char in "\u25b3\u2206\u0394"):
        return True
    return compact in {"47", "07", "c", "C"}


def _merge_bodies(root_body: str, suffix_body: str | None) -> str:
    if suffix_body is None:
        return root_body
    if not root_body:
        return suffix_body
    if suffix_body.startswith(root_body):
        return suffix_body
    if root_body.startswith(suffix_body):
        return root_body
    if root_body == "7" and suffix_body.startswith(("b", "#")):
        return f"7{suffix_body}"
    if root_body == "7" and suffix_body.startswith("7"):
        return suffix_body
    if len(suffix_body) > len(root_body):
        return suffix_body
    return root_body


def _nearest_related_token(
    root_token: OCRToken,
    candidates: list[OCRToken],
    *,
    max_distance: float,
    next_root_x: float | None,
) -> OCRToken | None:
    related: list[tuple[float, OCRToken]] = []
    for token in candidates:
        if token.cx < root_token.cx - 16.0:
            continue
        if next_root_x is not None and token.cx >= next_root_x - 8.0:
            continue
        distance = abs(token.cx - root_token.cx)
        if distance <= max_distance:
            related.append((distance, token))

    if not related:
        return None
    return min(related, key=lambda item: item[0])[1]


def _related_tokens(
    root_token: OCRToken,
    candidates: list[OCRToken],
    *,
    max_distance: float,
    next_root_x: float | None,
) -> list[OCRToken]:
    related: list[OCRToken] = []
    for token in candidates:
        if token.cx < root_token.cx - 16.0:
            continue
        if next_root_x is not None and token.cx >= next_root_x - 8.0:
            continue
        if abs(token.cx - root_token.cx) <= max_distance:
            related.append(token)
    return sorted(related, key=lambda token: token.cx)


def _combine_suffix_token_bodies(
    tokens: list[OCRToken],
    *,
    image: np.ndarray | None,
    root: _RootCandidate | None = None,
    accidental_token: OCRToken | None = None,
) -> str | None:
    body_records = [
        (token, body)
        for token in tokens
        if (
            body := _body_from_suffix_token(
                token,
                image=image,
                root=root,
                accidental_token=accidental_token,
            )
        )
        is not None
    ]
    precise_bodies = [
        body
        for token, body in body_records
        if token.region == "suffix_lower_right"
    ]
    bodies = precise_bodies or [body for _token, body in body_records]
    if not bodies:
        return None

    for body in bodies:
        if body.startswith(("m", "maj", "dim", "aug", "sus", "add", "alt")):
            return body

    altered_sevenths = [body for body in bodies if re.fullmatch(r"7(?:[#b](?:5|9|11|13))+", body)]
    if altered_sevenths:
        return max(altered_sevenths, key=len)

    if "7" in bodies:
        alterations = [
            body
            for body in bodies
            if re.fullmatch(r"[#b](?:5|9|11|13)", body)
        ]
        if alterations:
            return "7" + "".join(alterations)
        return "7"

    return max(bodies, key=len)


def _has_related_invalid_suffix(
    root_token: OCRToken,
    candidates: list[OCRToken],
    *,
    max_distance: float,
    next_root_x: float | None,
    image: np.ndarray | None,
    root: _RootCandidate | None = None,
    accidental_token: OCRToken | None = None,
) -> bool:
    for token in candidates:
        if token.cx < root_token.cx - 16.0:
            continue
        if next_root_x is not None and token.cx >= next_root_x - 8.0:
            continue
        if abs(token.cx - root_token.cx) > max_distance:
            continue
        if (
            _body_from_suffix_token(
                token,
                image=image,
                root=root,
                accidental_token=accidental_token,
            )
            is None
        ):
            return True
    return False


def _suffix_has_minor_dash(token: OCRToken, image: np.ndarray) -> bool:
    binary = _token_binary_crop(token, image, pad=8)
    if binary is None:
        return False

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    crop_height, crop_width = binary.shape[:2]
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 8:
            continue
        aspect = width / max(float(height), 1.0)
        center_x = x + width / 2.0
        center_y = y + height / 2.0
        if (
            aspect >= 2.0
            and width >= max(8, crop_width * 0.08)
            and height <= max(8, crop_height * 0.18)
            and center_x <= crop_width * 0.52
            and crop_height * 0.18 <= center_y <= crop_height * 0.82
        ):
            return True

    return False


def _suffix_has_triangle(token: OCRToken, image: np.ndarray) -> bool:
    crop = _token_image_crop(token, image, pad=8)
    if crop is None:
        return False
    return visual_suffix_has_triangle(crop)


def _token_binary_crop(token: OCRToken, image: np.ndarray, *, pad: int) -> np.ndarray | None:
    crop = _token_image_crop(token, image, pad=pad)
    if crop is None:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _threshold, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    return binary


def _token_image_crop(token: OCRToken, image: np.ndarray, *, pad: int) -> np.ndarray | None:
    height, width = image.shape[:2]
    x0, y0, x1, y1 = [int(round(value)) for value in token.bbox]
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(width, x1 + pad)
    y1 = min(height, y1 + pad)
    if x1 <= x0 or y1 <= y0:
        return None

    return image[y0:y1, x0:x1]


def _measure_width(tokens: list[OCRToken]) -> float:
    if not tokens:
        return 1.0
    x0 = min(token.bbox[0] for token in tokens)
    x1 = max(token.bbox[2] for token in tokens)
    return max(1.0, x1 - x0)


def _union_bbox(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _combined_confidence(tokens: list[OCRToken]) -> float | None:
    confidences = [
        float(token.confidence)
        for token in tokens
        if isinstance(token.confidence, int | float)
    ]
    if not confidences:
        return None
    return min(confidences)


def _diagnostic(
    *,
    measure_index: int,
    status: str,
    text: str,
    root: _RootCandidate,
    accidental_token: OCRToken | None,
    suffix_tokens: list[OCRToken],
    reason: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "measure_index": measure_index,
        "status": status,
        "text": text,
        "fragments": [
            {"role": "root", **root.token.to_dict()},
        ],
    }
    if accidental_token is not None:
        payload["fragments"].append(
            {"role": "accidental", **accidental_token.to_dict()}
        )
    for suffix_token in suffix_tokens:
        payload["fragments"].append({"role": "suffix", **suffix_token.to_dict()})
    if reason is not None:
        payload["reason"] = reason
    return payload
