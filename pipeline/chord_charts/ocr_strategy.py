from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.chord_charts.chord_symbol import ParsedChord, parse_chord_symbol
from pipeline.chord_charts.ocr_backend import OCRToken


@dataclass(frozen=True)
class ChartMeasureRegion:
    index: int
    row_index: int
    col_index: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class ChartOCRCandidate:
    measure_index: int
    text_raw: str
    text_norm: str
    source: str
    confidence: float | None
    bbox: tuple[float, float, float, float]
    parsed: ParsedChord


@dataclass(frozen=True)
class SelectiveCellOCRPlan:
    measure_indices: list[int]
    diagnostics: dict[str, Any]


@dataclass
class _MeasureEvidence:
    region: ChartMeasureRegion
    candidates: list[ChartOCRCandidate] = field(default_factory=list)
    suffix_fragments: list[dict[str, Any]] = field(default_factory=list)
    chord_like_fragments: list[dict[str, Any]] = field(default_factory=list)
    repeat_tokens: list[dict[str, Any]] = field(default_factory=list)


def plan_selective_chart_cell_ocr(
    *,
    rows: list[Any],
    page_tokens: list[OCRToken],
    row_tokens: list[OCRToken],
    low_confidence: float = 0.55,
) -> SelectiveCellOCRPlan:
    regions = build_chart_measure_regions(rows)
    evidence_by_measure = {
        region.index: _MeasureEvidence(region=region) for region in regions
    }

    for token in _expand_chart_tokens([*page_tokens, *row_tokens]):
        measure = _measure_for_token(token, regions)
        if measure is None:
            continue

        evidence = evidence_by_measure[measure.index]
        parsed = parse_chord_symbol(token.text)
        if parsed is not None:
            evidence.candidates.append(
                ChartOCRCandidate(
                    measure_index=measure.index,
                    text_raw=token.text,
                    text_norm=parsed.text_norm,
                    source=token.source,
                    confidence=token.confidence,
                    bbox=token.bbox,
                    parsed=parsed,
                )
            )
            continue

        fragment = {
            "text": token.text,
            "bbox": list(token.bbox),
            "confidence": token.confidence,
            "source": token.source,
        }
        if "%" in token.text:
            evidence.repeat_tokens.append(fragment)
        elif _is_suffix_like_fragment(token.text):
            evidence.suffix_fragments.append(fragment)
        elif _is_chord_like_fragment(token.text):
            evidence.chord_like_fragments.append(fragment)

    selected: list[dict[str, Any]] = []
    for evidence in evidence_by_measure.values():
        reasons = _suspicion_reasons(evidence, low_confidence=low_confidence)
        if not reasons:
            continue

        selected.append(
            {
                "measure_index": evidence.region.index,
                "row_index": evidence.region.row_index,
                "col_index": evidence.region.col_index,
                "reasons": reasons,
                "candidates": [
                    _candidate_payload(candidate) for candidate in evidence.candidates
                ],
                "suffix_fragments": evidence.suffix_fragments,
                "chord_like_fragments": evidence.chord_like_fragments,
                "repeat_tokens": evidence.repeat_tokens,
            }
        )

    measure_indices = [item["measure_index"] for item in selected]
    return SelectiveCellOCRPlan(
        measure_indices=measure_indices,
        diagnostics={
            "mode": "page_row_selective_cell_fallback",
            "low_confidence_threshold": low_confidence,
            "measure_count": len(regions),
            "selected_measure_count": len(measure_indices),
            "selected_measure_indices": measure_indices,
            "selected_measures": selected,
            "rules": [
                "page_row_disagreement",
                "contained_shorter_longer_chord",
                "low_confidence_candidate",
                "plain_major_or_minor_candidate",
                "no_chord_candidate_but_chord_like_ocr",
                "suffix_fragment_near_candidate",
                "root_accidental_quality_or_extension_disagreement",
                "repeat_symbol_with_chord_candidate",
            ],
        },
    )


def plan_multi_chord_chart_cell_ocr(
    *,
    rows: list[Any],
    page_tokens: list[OCRToken],
    row_tokens: list[OCRToken],
) -> SelectiveCellOCRPlan:
    regions = build_chart_measure_regions(rows)
    evidence_by_measure = {
        region.index: _MeasureEvidence(region=region) for region in regions
    }

    raw_tokens_by_measure: dict[int, list[OCRToken]] = {
        region.index: [] for region in regions
    }
    for token in [*page_tokens, *row_tokens]:
        measure = _measure_for_token(token, regions)
        if measure is not None:
            raw_tokens_by_measure[measure.index].append(token)

    for token in _expand_chart_tokens([*page_tokens, *row_tokens]):
        measure = _measure_for_token(token, regions)
        if measure is None:
            continue

        evidence = evidence_by_measure[measure.index]
        fragment = {
            "text": token.text,
            "bbox": list(token.bbox),
            "confidence": token.confidence,
            "source": token.source,
        }
        if _is_chord_like_fragment(token.text):
            evidence.chord_like_fragments.append(fragment)
        elif _is_suffix_like_fragment(token.text):
            evidence.suffix_fragments.append(fragment)

    selected: list[dict[str, Any]] = []
    for measure_index, evidence in evidence_by_measure.items():
        reasons = _multi_chord_reasons(
            evidence,
            raw_tokens=raw_tokens_by_measure.get(measure_index, []),
        )
        if not reasons:
            continue

        selected.append(
            {
                "measure_index": evidence.region.index,
                "row_index": evidence.region.row_index,
                "col_index": evidence.region.col_index,
                "reasons": reasons,
                "root_anchor_hints": _root_anchor_hints(
                    evidence,
                    raw_tokens=raw_tokens_by_measure.get(measure_index, []),
                ),
                "chord_like_fragments": evidence.chord_like_fragments,
                "suffix_fragments": evidence.suffix_fragments,
                "raw_tokens": [
                    {
                        "text": token.text,
                        "bbox": list(token.bbox),
                        "confidence": token.confidence,
                        "source": token.source,
                    }
                    for token in raw_tokens_by_measure.get(measure_index, [])
                ],
            }
        )

    measure_indices = [item["measure_index"] for item in selected]
    return SelectiveCellOCRPlan(
        measure_indices=measure_indices,
        diagnostics={
            "mode": "page_row_multi_chord_supplemental_cell_ocr",
            "measure_count": len(regions),
            "selected_measure_count": len(measure_indices),
            "selected_measure_indices": measure_indices,
            "selected_measures": selected,
            "rules": [
                "wide_ocr_token_with_internal_space",
                "multiple_chord_like_fragments",
                "right_half_chord_like_fragment",
            ],
        },
    )


def root_anchor_hints_from_plan(plan: SelectiveCellOCRPlan) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for item in plan.diagnostics.get("selected_measures") or []:
        if not isinstance(item, dict):
            continue
        for hint in item.get("root_anchor_hints") or []:
            if isinstance(hint, dict):
                hints.append(hint)
    return hints


def build_chart_measure_regions(rows: list[Any]) -> list[ChartMeasureRegion]:
    regions: list[ChartMeasureRegion] = []
    measure_index = 1
    for row in rows:
        boundaries = getattr(row, "boundaries", [])
        for col_index, (left, right) in enumerate(
            zip(boundaries, boundaries[1:]),
            start=1,
        ):
            if float(right.x) <= float(left.x):
                continue

            regions.append(
                ChartMeasureRegion(
                    index=measure_index,
                    row_index=int(getattr(row, "index")),
                    col_index=col_index,
                    bbox=(
                        float(left.x),
                        float(row.y_top),
                        float(right.x),
                        float(row.y_bottom),
                    ),
                )
            )
            measure_index += 1

    return regions


def _suspicion_reasons(
    evidence: _MeasureEvidence,
    *,
    low_confidence: float,
) -> list[str]:
    reasons: list[str] = []
    candidates = evidence.candidates
    if not candidates:
        if evidence.suffix_fragments or evidence.chord_like_fragments:
            reasons.append("no_chord_candidate_but_chord_like_ocr")
        return reasons

    candidate_norms_by_source = _candidate_norms_by_source(candidates)
    if (
        candidate_norms_by_source.get("page")
        and candidate_norms_by_source.get("row")
        and candidate_norms_by_source["page"] != candidate_norms_by_source["row"]
    ):
        reasons.append("page_row_disagreement")

    if any(
        float(candidate.confidence or 0.0) < low_confidence
        for candidate in candidates
    ):
        reasons.append("low_confidence_candidate")

    if any(_is_plain_major_or_minor_candidate(candidate) for candidate in candidates):
        reasons.append("plain_major_or_minor_candidate")

    if _has_contained_shorter_longer_chord(candidates):
        reasons.append("contained_shorter_longer_chord")

    if _has_component_disagreement(candidates):
        reasons.append("root_accidental_quality_or_extension_disagreement")

    if evidence.suffix_fragments:
        reasons.append("suffix_fragment_near_candidate")

    if evidence.repeat_tokens and candidates:
        reasons.append("repeat_symbol_with_chord_candidate")

    return reasons


def _multi_chord_reasons(
    evidence: _MeasureEvidence,
    *,
    raw_tokens: list[OCRToken],
) -> list[str]:
    reasons: list[str] = []
    measure_width = max(1.0, evidence.region.bbox[2] - evidence.region.bbox[0])

    if any(
        len(token.text.split()) > 1
        and (token.bbox[2] - token.bbox[0]) >= measure_width * 0.42
        for token in raw_tokens
    ):
        reasons.append("wide_ocr_token_with_internal_space")

    chord_like_centers = [
        _relative_center_x(fragment["bbox"], evidence.region)
        for fragment in evidence.chord_like_fragments
    ]
    if (
        len(chord_like_centers) >= 2
        and max(chord_like_centers) - min(chord_like_centers) >= 0.32
    ):
        reasons.append("multiple_chord_like_fragments")

    if any(center >= 0.55 for center in chord_like_centers):
        reasons.append("right_half_chord_like_fragment")

    return reasons


def _root_anchor_hints(
    evidence: _MeasureEvidence,
    *,
    raw_tokens: list[OCRToken],
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for token in raw_tokens:
        if len(token.text.split()) > 1:
            hints.extend(
                _root_anchor_hints_from_text(
                    token.text,
                    token.bbox,
                    confidence=token.confidence,
                    source=token.source,
                    region=evidence.region,
                    source_kind="raw_token",
                )
            )

    for fragment in evidence.chord_like_fragments:
        hints.extend(
            _root_anchor_hints_from_text(
                str(fragment.get("text") or ""),
                tuple(float(value) for value in fragment.get("bbox") or ()),
                confidence=fragment.get("confidence"),
                source=str(fragment.get("source") or ""),
                region=evidence.region,
                source_kind="chord_like_fragment",
            )
        )

    return _deduplicate_root_anchor_hints(hints, region=evidence.region)


def _root_anchor_hints_from_text(
    text: str,
    bbox: tuple[float, ...],
    *,
    confidence: Any,
    source: str,
    region: ChartMeasureRegion,
    source_kind: str,
) -> list[dict[str, Any]]:
    if len(bbox) != 4:
        return []
    roots: list[dict[str, Any]] = []
    total_chars = max(1, len(text))
    x0, y0, x1, y1 = [float(value) for value in bbox]
    char_width = max(1.0, x1 - x0) / total_chars

    spans = list(re.finditer(r"\S+", text)) if " " in text else [None]
    for span in spans:
        span_start = span.start() if span is not None else 0
        span_text = span.group(0) if span is not None else text
        match = re.search(r"[A-Ga-g]", span_text)
        if match is None:
            continue

        char_index = span_start + match.start()
        hx0 = x0 + char_width * char_index
        hx1 = x0 + char_width * (char_index + 1)
        roots.append(
            {
                "measure_index": region.index,
                "row_index": region.row_index,
                "col_index": region.col_index,
                "root": match.group(0).upper(),
                "center_x": (hx0 + hx1) / 2.0,
                "bbox": [hx0, y0, hx1, y1],
                "confidence": confidence,
                "source": source,
                "source_kind": source_kind,
                "source_text": text,
                "source_bbox": [x0, y0, x1, y1],
            }
        )
    return roots


def _deduplicate_root_anchor_hints(
    hints: list[dict[str, Any]],
    *,
    region: ChartMeasureRegion,
) -> list[dict[str, Any]]:
    if not hints:
        return []
    threshold = max(24.0, (region.bbox[2] - region.bbox[0]) * 0.08)
    groups: list[list[dict[str, Any]]] = []
    for hint in sorted(hints, key=lambda item: float(item["center_x"])):
        center_x = float(hint["center_x"])
        if (
            not groups
            or abs(center_x - _hint_group_center(groups[-1])) > threshold
        ):
            groups.append([hint])
        else:
            groups[-1].append(hint)

    deduped: list[dict[str, Any]] = []
    for anchor_index, group in enumerate(groups, start=1):
        hint = max(group, key=_root_anchor_hint_score)
        deduped.append({**hint, "anchor_index": anchor_index})
    return deduped


def _hint_group_center(group: list[dict[str, Any]]) -> float:
    return sum(float(item["center_x"]) for item in group) / len(group)


def _root_anchor_hint_score(hint: dict[str, Any]) -> float:
    confidence = hint.get("confidence")
    score = float(confidence) if isinstance(confidence, int | float) else 0.0
    if hint.get("source_kind") == "chord_like_fragment":
        score += 0.2
    return score


def _relative_center_x(
    bbox: object,
    region: ChartMeasureRegion,
) -> float:
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return 0.0
    measure_width = max(1.0, region.bbox[2] - region.bbox[0])
    center_x = (float(bbox[0]) + float(bbox[2])) / 2.0
    return (center_x - region.bbox[0]) / measure_width


def _candidate_norms_by_source(
    candidates: list[ChartOCRCandidate],
) -> dict[str, set[str]]:
    by_source: dict[str, set[str]] = {}
    for candidate in candidates:
        by_source.setdefault(_source_family(candidate.source), set()).add(
            candidate.text_norm
        )
    return by_source


def _source_family(source: str) -> str:
    if source == "page_ocr":
        return "page"
    if source.startswith("cell_ocr_row"):
        return "row"
    if source.startswith("cell_ocr"):
        return "cell"
    return source


def _has_contained_shorter_longer_chord(
    candidates: list[ChartOCRCandidate],
) -> bool:
    norms = sorted({candidate.text_norm for candidate in candidates}, key=len)
    for index, shorter in enumerate(norms):
        for longer in norms[index + 1 :]:
            if len(longer) <= len(shorter):
                continue
            if longer.startswith(shorter) or shorter in longer:
                return True
    return False


def _has_component_disagreement(
    candidates: list[ChartOCRCandidate],
) -> bool:
    if len(candidates) < 2:
        return False

    signatures = {
        (
            candidate.parsed.root,
            candidate.parsed.accidental,
            candidate.parsed.quality,
            tuple(candidate.parsed.extensions),
            tuple(candidate.parsed.alterations),
            candidate.parsed.bass,
        )
        for candidate in candidates
    }
    return len(signatures) > 1


def _is_plain_major_or_minor_candidate(candidate: ChartOCRCandidate) -> bool:
    parsed = candidate.parsed
    if parsed.extensions or parsed.alterations or parsed.bass:
        return False
    return parsed.quality in {"major", "minor"}


def _measure_for_token(
    token: OCRToken,
    measures: list[ChartMeasureRegion],
) -> ChartMeasureRegion | None:
    candidates = [
        measure
        for measure in measures
        if measure.bbox[0] - 8 <= token.cx <= measure.bbox[2] + 8
        and measure.bbox[1] - 60 <= token.cy <= measure.bbox[3] + 60
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda measure: (
            abs(token.cy - ((measure.bbox[1] + measure.bbox[3]) / 2.0)),
            abs(token.cx - ((measure.bbox[0] + measure.bbox[2]) / 2.0)),
        ),
    )


def _expand_chart_tokens(tokens: list[OCRToken]) -> list[OCRToken]:
    expanded: list[OCRToken] = []
    for token in tokens:
        parts = token.text.split()
        if len(parts) <= 1:
            expanded.append(token)
            continue

        x0, y0, x1, y1 = token.bbox
        total_chars = sum(len(part) for part in parts)
        if total_chars == 0:
            expanded.append(token)
            continue

        cursor = x0
        width = x1 - x0
        for part in parts:
            part_width = width * (len(part) / total_chars)
            expanded.append(
                OCRToken(
                    text=part,
                    bbox=(cursor, y0, cursor + part_width, y1),
                    confidence=token.confidence,
                    source=token.source,
                )
            )
            cursor += part_width

    return expanded


def _is_suffix_like_fragment(text: str) -> bool:
    compact = _compact_fragment(text)
    return bool(
        re.fullmatch(
            r"(?:[#b]?(?:5|6|7|9|11|13)|m|maj|M|dim|aug|sus|add|alt|-|o|0)",
            compact,
        )
    )


def _is_chord_like_fragment(text: str) -> bool:
    compact = _compact_fragment(text)
    if len(compact) > 16:
        return False
    if parse_chord_symbol(compact) is not None:
        return True
    if re.search(r"[A-Ga-g]", compact) and re.search(r"[#b0-9zZmM+\-]", compact):
        return True
    return _is_suffix_like_fragment(compact)


def _compact_fragment(text: str) -> str:
    compact = re.sub(r"\s+", "", text.strip())
    compact = compact.replace("\u266d", "b").replace("\ue260", "b")
    compact = compact.replace("\u266f", "#").replace("\ue262", "#")
    compact = compact.replace("\u2212", "-")
    compact = compact.replace("\u2013", "-").replace("\u2014", "-")
    compact = compact.replace("\u25b3", "maj")
    compact = compact.replace("\u2206", "maj").replace("\u0394", "maj")
    compact = compact.replace("\u00f8", "m7b5").replace("\u00b0", "dim")
    return compact.strip(".,;:!|")


def _candidate_payload(candidate: ChartOCRCandidate) -> dict[str, Any]:
    return {
        "text": candidate.text_raw,
        "text_norm": candidate.text_norm,
        "source": candidate.source,
        "confidence": candidate.confidence,
        "bbox": list(candidate.bbox),
    }
