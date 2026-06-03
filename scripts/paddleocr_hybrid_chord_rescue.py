from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.chords.candidate_resolution import resolve_chord_ocr_text
from pipeline.chords.measure_assignment import assign_chords_to_measures
from pipeline.chords.models import ChordToken
from pipeline.chords.token_filters import filter_probable_non_chords, serialize_token


DEFAULT_SAMPLES = {
    "afternoon_in_paris": Path(
        "storage/jobs/bench-handwritten-ocr-split-merge-afternoon-in-paris-20260604/output"
    ),
    "airegin": Path(
        "storage/jobs/bench-handwritten-ocr-split-merge-airegin-20260604/output"
    ),
    "agua_de_beber": Path(
        "storage/jobs/bench-handwritten-ocr-split-merge-agua-de-beber-20260604/output"
    ),
}

_ROOTS = set("ABCDEFG")
_COMMON_ADDITION_SUFFIXES = {
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
    "-7b5",
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
}


@dataclass(frozen=True)
class RescueRegion:
    source: str
    system_index: int | None
    bbox: tuple[int, int, int, int]
    triggers: tuple[dict[str, Any], ...]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run PaddleOCR only on high-risk EasyOCR chord regions from saved "
            "HOMR/EasyOCR benchmark outputs."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="storage/jobs/bench-paddleocr-hybrid-rescue-20260604/output",
        help="Directory where JSON summaries and diagnostic overlays are written.",
    )
    parser.add_argument(
        "--cache-root",
        default=None,
        help="Writable Paddle/PaddleX cache root. Defaults to %%TEMP%%/musicvision-paddle-home.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.15,
        help="Minimum PaddleOCR score before an otherwise valid chord is accepted.",
    )
    parser.add_argument(
        "--accepted-confidence-threshold",
        type=float,
        default=0.50,
        help=(
            "EasyOCR accepted tokens at or below this confidence are also checked "
            "with PaddleOCR. Use a negative value to disable accepted-token rescue."
        ),
    )
    parser.add_argument(
        "--padding-x",
        type=int,
        default=36,
        help="Horizontal padding added around EasyOCR trigger boxes.",
    )
    parser.add_argument(
        "--padding-y",
        type=int,
        default=28,
        help="Vertical padding added around EasyOCR trigger boxes.",
    )
    parser.add_argument(
        "--text-det-limit-side-len",
        type=int,
        default=None,
        help="Optional PaddleOCR text_det_limit_side_len override.",
    )
    parser.add_argument(
        "--text-det-limit-type",
        default=None,
        choices=("min", "max"),
        help="Optional PaddleOCR text_det_limit_type override.",
    )
    parser.add_argument(
        "--apply-replacements",
        action="store_true",
        help=(
            "Apply conservative same-root PaddleOCR replacements in the generated "
            "hybrid token list. By default replacements are reported as candidates only."
        ),
    )
    args = parser.parse_args()

    cache_root = (
        Path(args.cache_root)
        if args.cache_root
        else Path(os.environ.get("TEMP", ".")) / "musicvision-paddle-home"
    )
    configure_paddle_environment(cache_root)

    from paddleocr import PaddleOCR

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    ocr = PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        text_det_limit_side_len=args.text_det_limit_side_len,
        text_det_limit_type=args.text_det_limit_type,
    )
    warmup_seconds = time.perf_counter() - started

    summaries = []
    for sample_name, sample_output_dir in DEFAULT_SAMPLES.items():
        summaries.append(
            run_sample(
                sample_name=sample_name,
                sample_output_dir=sample_output_dir,
                output_dir=output_dir,
                ocr=ocr,
                min_confidence=args.min_confidence,
                accepted_confidence_threshold=args.accepted_confidence_threshold,
                padding_x=args.padding_x,
                padding_y=args.padding_y,
                apply_replacements=args.apply_replacements,
            )
        )

    payload = {
        "benchmark_type": "paddleocr_hybrid_chord_rescue",
        "pipeline": "saved_easyocr_high_risk_regions_paddleocr_rescue",
        "homr_rerun": False,
        "paddleocr_warmup_seconds": round(warmup_seconds, 3),
        "paddleocr_options": {
            "text_det_limit_side_len": args.text_det_limit_side_len,
            "text_det_limit_type": args.text_det_limit_type,
            "min_confidence": args.min_confidence,
            "accepted_confidence_threshold": args.accepted_confidence_threshold,
            "padding_x": args.padding_x,
            "padding_y": args.padding_y,
            "apply_replacements": args.apply_replacements,
        },
        "samples": summaries,
        "notes": [
            "EasyOCR remains the baseline; PaddleOCR runs only on rejected or high-risk accepted EasyOCR boxes.",
            "PaddleOCR root-plus-suffix fragments are merged before chord resolution.",
            "Replacement candidates are reported for review; use --apply-replacements to include conservative same-root replacements in the generated hybrid token list.",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))


def configure_paddle_environment(cache_root: Path) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(cache_root)
    os.environ["HOME"] = str(cache_root)
    os.environ["XDG_CACHE_HOME"] = str(cache_root / ".cache")
    os.environ["PADDLE_HOME"] = str(cache_root / ".cache" / "paddle")
    os.environ.setdefault(
        "PADDLE_PDX_CACHE_HOME",
        str(Path(os.environ.get("TEMP", ".")) / "musicvision-paddlex-cache"),
    )
    os.environ.setdefault("FLAGS_enable_pir_api", "0")


def run_sample(
    *,
    sample_name: str,
    sample_output_dir: Path,
    output_dir: Path,
    ocr: Any,
    min_confidence: float,
    accepted_confidence_threshold: float,
    padding_x: int,
    padding_y: int,
    apply_replacements: bool,
) -> dict[str, Any]:
    processed_image_path = sample_output_dir / "homr_processed.png"
    geometry_path = sample_output_dir / "geometry.json"
    baseline_path = sample_output_dir / "chord_assignments.json"
    if not processed_image_path.exists() or not geometry_path.exists() or not baseline_path.exists():
        raise FileNotFoundError(
            f"Missing saved benchmark artifacts for {sample_name}: {sample_output_dir}"
        )

    image_bgr = cv2.imread(str(processed_image_path))
    if image_bgr is None:
        raise RuntimeError(f"Could not read {processed_image_path}")
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_diagnostics = baseline_payload.get("chord_ocr") or {}
    baseline_tokens = chord_tokens_from_payload(
        baseline_diagnostics.get("accepted_tokens") or []
    )

    regions = build_rescue_regions(
        image_shape=image_bgr.shape,
        baseline_diagnostics=baseline_diagnostics,
        accepted_confidence_threshold=accepted_confidence_threshold,
        padding_x=padding_x,
        padding_y=padding_y,
    )

    started = time.perf_counter()
    raw_hits: list[dict[str, Any]] = []
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        crop = image_bgr[y0:y1, x0:x1]
        for result in ocr.predict(crop):
            raw_hits.extend(parse_result(result, offset=(x0, y0), region=region))
    elapsed = time.perf_counter() - started

    raw_hits = dedupe_hits(raw_hits)
    paddle_tokens, paddle_rejects, fragment_merges = resolve_paddle_hits(
        raw_hits,
        min_confidence=min_confidence,
    )
    hybrid = build_hybrid_tokens(
        baseline_tokens=baseline_tokens,
        paddle_tokens=paddle_tokens,
        accepted_confidence_threshold=accepted_confidence_threshold,
        apply_replacements=apply_replacements,
    )
    filtered_hybrid_tokens, filtered_hits = filter_probable_non_chords(
        tokens=hybrid["tokens"],
        image=image_rgb,
        geometry=geometry,
    )
    chord_result = assign_chords_to_measures(
        tokens=filtered_hybrid_tokens,
        geometry=geometry,
        image=image_rgb,
        source_path=processed_image_path.name,
        time_signature=str(baseline_payload.get("time_signature") or "4/4"),
        beats_per_bar=int(baseline_payload.get("beats_per_bar") or 4),
    )

    overlay_path = output_dir / f"{sample_name}_hybrid_rescue_overlay.png"
    write_hybrid_overlay(
        image=image_bgr,
        baseline_tokens=baseline_tokens,
        rescue_regions=regions,
        additions=hybrid["additions"],
        replacement_candidates=hybrid["replacement_candidates"],
        replacements_applied=hybrid["replacements_applied"],
        rejected=paddle_rejects,
        output_path=overlay_path,
    )

    sample_payload = {
        "sample": sample_name,
        "source_output_dir": str(sample_output_dir).replace("\\", "/"),
        "paddleocr_seconds": round(elapsed, 3),
        "baseline_accepted_tokens": len(baseline_tokens),
        "baseline_rejected_hits": len(baseline_diagnostics.get("rejected_hits") or []),
        "baseline_filtered_hits": len(baseline_diagnostics.get("filtered_hits") or []),
        "rescue_regions": len(regions),
        "rescue_region_triggers": [
            {
                "source": region.source,
                "system_index": region.system_index,
                "bbox": list(region.bbox),
                "triggers": list(region.triggers),
            }
            for region in regions
        ],
        "paddle_raw_hits": len(raw_hits),
        "paddle_fragment_merges": len(fragment_merges),
        "paddle_accepted_hits": len(paddle_tokens),
        "paddle_rejected_hits": len(paddle_rejects),
        "paddle_tokens": [serialize_token(token) for token in paddle_tokens],
        "paddle_rejects": paddle_rejects,
        "fragment_merges": fragment_merges,
        "duplicate_hits": len(hybrid["duplicates"]),
        "additions": hybrid["additions"],
        "suppressed_additions": hybrid["suppressed_additions"],
        "replacement_candidates": hybrid["replacement_candidates"],
        "replacements_applied": hybrid["replacements_applied"],
        "hybrid_accepted_tokens_before_filters": len(hybrid["tokens"]),
        "hybrid_accepted_tokens": len(filtered_hybrid_tokens),
        "hybrid_filtered_hits": filtered_hits,
        "hybrid_chord_ocr": {
            "backend": "easyocr+paddleocr_hybrid_experiment",
            "accepted_tokens": [serialize_token(token) for token in filtered_hybrid_tokens],
            "rejected_hits": [
                *(baseline_diagnostics.get("rejected_hits") or []),
                *paddle_rejects,
            ],
            "filtered_hits": filtered_hits,
            "paddle_rescue": {
                "regions": len(regions),
                "seconds": round(elapsed, 3),
                "raw_hits": len(raw_hits),
                "accepted_hits": len(paddle_tokens),
                "fragment_merges": len(fragment_merges),
                "additions": len(hybrid["additions"]),
                "suppressed_additions": len(hybrid["suppressed_additions"]),
                "replacement_candidates": len(hybrid["replacement_candidates"]),
                "replacements_applied": len(hybrid["replacements_applied"]),
                "apply_replacements": apply_replacements,
            },
        },
        "pages": chord_result["pages"],
        "overlay_file": overlay_path.name,
    }
    (output_dir / f"{sample_name}.json").write_text(
        json.dumps(sample_payload, indent=2),
        encoding="utf-8",
    )
    return {
        key: value
        for key, value in sample_payload.items()
        if key
        not in {
            "paddle_tokens",
            "paddle_rejects",
            "fragment_merges",
            "rescue_region_triggers",
            "additions",
            "suppressed_additions",
            "replacement_candidates",
            "replacements_applied",
            "hybrid_chord_ocr",
            "pages",
            "hybrid_filtered_hits",
        }
    }


def chord_tokens_from_payload(values: list[dict[str, Any]]) -> list[ChordToken]:
    tokens = []
    for value in values:
        bbox = coerce_payload_bbox(value.get("bbox"))
        if bbox is None:
            continue
        tokens.append(
            ChordToken(
                text_raw=str(value.get("text_raw") or value.get("text") or ""),
                text_norm=str(value.get("text_norm") or ""),
                bbox=bbox,
                confidence=coerce_float(value.get("conf")),
                system_index=coerce_int(value.get("system_index")),
            )
        )
    return tokens


def build_rescue_regions(
    *,
    image_shape: tuple[int, ...],
    baseline_diagnostics: dict[str, Any],
    accepted_confidence_threshold: float,
    padding_x: int,
    padding_y: int,
) -> list[RescueRegion]:
    height, width = image_shape[:2]
    regions: list[RescueRegion] = []

    for hit in baseline_diagnostics.get("rejected_hits") or []:
        if not rejected_hit_needs_rescue(hit):
            continue
        region = rescue_region_from_payload(
            hit,
            source="easyocr_rejected_hit",
            width=width,
            height=height,
            padding_x=padding_x,
            padding_y=padding_y,
        )
        if region is not None:
            regions.append(region)

    if accepted_confidence_threshold >= 0:
        for hit in baseline_diagnostics.get("accepted_tokens") or []:
            if not accepted_hit_needs_rescue(
                hit,
                accepted_confidence_threshold=accepted_confidence_threshold,
            ):
                continue
            region = rescue_region_from_payload(
                hit,
                source="easyocr_high_risk_accepted",
                width=width,
                height=height,
                padding_x=padding_x,
                padding_y=padding_y,
            )
            if region is not None:
                regions.append(region)

    return merge_rescue_regions(regions)


def rejected_hit_needs_rescue(hit: dict[str, Any]) -> bool:
    if hit.get("candidate_kind") == "uncertain_chord":
        return True
    text = str(hit.get("text") or hit.get("text_raw") or hit.get("text_norm") or "")
    return starts_with_chord_root(text)


def accepted_hit_needs_rescue(
    hit: dict[str, Any],
    *,
    accepted_confidence_threshold: float,
) -> bool:
    conf = coerce_float(hit.get("conf"))
    text_raw = str(hit.get("text_raw") or hit.get("text") or "")
    text_norm = str(hit.get("text_norm") or "")
    if conf is not None and conf <= accepted_confidence_threshold:
        return True
    if high_risk_chord_text(text_norm):
        return True
    if text_raw != text_norm and conf is not None and conf <= 0.65:
        return True
    return False


def rescue_region_from_payload(
    payload: dict[str, Any],
    *,
    source: str,
    width: int,
    height: int,
    padding_x: int,
    padding_y: int,
) -> RescueRegion | None:
    bbox = coerce_payload_bbox(payload.get("bbox"))
    if bbox is None:
        return None

    x0, y0, x1, y1 = bbox
    region_bbox = (
        max(0, int(round(x0)) - padding_x),
        max(0, int(round(y0)) - padding_y),
        min(width, int(round(x1)) + padding_x),
        min(height, int(round(y1)) + padding_y),
    )
    if region_bbox[2] - region_bbox[0] < 8 or region_bbox[3] - region_bbox[1] < 8:
        return None

    return RescueRegion(
        source=source,
        system_index=coerce_int(payload.get("system_index")),
        bbox=region_bbox,
        triggers=(compact_trigger(payload),),
    )


def merge_rescue_regions(regions: list[RescueRegion]) -> list[RescueRegion]:
    merged: list[RescueRegion] = []

    for region in sorted(regions, key=lambda item: (item.bbox[1], item.bbox[0])):
        merge_index = matching_region_index(region, merged)
        if merge_index is None:
            merged.append(region)
            continue

        current = merged[merge_index]
        merged[merge_index] = RescueRegion(
            source=f"{current.source}+{region.source}"
            if region.source not in current.source.split("+")
            else current.source,
            system_index=current.system_index
            if current.system_index is not None
            else region.system_index,
            bbox=(
                min(current.bbox[0], region.bbox[0]),
                min(current.bbox[1], region.bbox[1]),
                max(current.bbox[2], region.bbox[2]),
                max(current.bbox[3], region.bbox[3]),
            ),
            triggers=(*current.triggers, *region.triggers),
        )

    return merged


def matching_region_index(
    region: RescueRegion,
    candidates: list[RescueRegion],
) -> int | None:
    for index, current in enumerate(candidates):
        if region.system_index is not None and current.system_index is not None:
            if region.system_index != current.system_index:
                continue
        if bbox_iou(region.bbox, current.bbox) >= 0.25:
            return index
        if bbox_overlap_ratio(region.bbox, current.bbox) >= 0.65:
            return index
    return None


def parse_result(
    result: Any,
    *,
    offset: tuple[int, int],
    region: RescueRegion,
) -> list[dict[str, Any]]:
    data = result.res if hasattr(result, "res") else result
    texts = data.get("rec_texts") or []
    scores = data.get("rec_scores") or []
    boxes = data.get("rec_boxes")
    polys = data.get("rec_polys") or data.get("dt_polys") or []

    hits = []
    for index, text in enumerate(texts):
        score = float(scores[index]) if index < len(scores) else 0.0
        bbox = None
        if boxes is not None and index < len(boxes):
            bbox = coerce_paddle_box(boxes[index], offset=offset)
        elif index < len(polys):
            bbox = poly_to_bbox(polys[index], offset=offset)
        if bbox is None:
            continue
        hits.append(
            {
                "text": str(text),
                "score": score,
                "bbox": list(bbox),
                "source": "paddle_hybrid_rescue",
                "region_source": region.source,
                "system_index": region.system_index,
                "trigger_count": len(region.triggers),
            }
        )
    return hits


def resolve_paddle_hits(
    hits: list[dict[str, Any]],
    *,
    min_confidence: float,
) -> tuple[list[ChordToken], list[dict[str, Any]], list[dict[str, Any]]]:
    merged_hits, consumed_indexes, fragment_merges = merge_fragment_hits(hits)
    effective_hits = [
        *merged_hits,
        *(
            {**hit, "merge_role": "single"}
            for index, hit in enumerate(hits)
            if index not in consumed_indexes
        ),
    ]

    tokens = []
    rejects = []
    for hit in sorted(effective_hits, key=lambda item: (item["bbox"][1], item["bbox"][0])):
        raw_text = str(hit["text"]).strip()
        if not raw_text:
            continue
        score = float(hit["score"])
        resolution = resolve_chord_ocr_text(raw_text)
        hit["text_norm"] = resolution.text_norm
        hit["resolver_suggestions"] = resolution.suggestions
        hit["accepted_by_resolver"] = bool(resolution.accepted)

        if score >= min_confidence and resolution.accepted:
            tokens.append(
                ChordToken(
                    text_raw=raw_text,
                    text_norm=resolution.text_norm,
                    bbox=tuple(float(value) for value in hit["bbox"]),
                    confidence=score,
                    system_index=coerce_int(hit.get("system_index")),
                )
            )
            continue

        hit["reason"] = (
            f"confidence {score:.2f} < threshold {min_confidence:.2f}"
            if score < min_confidence
            else "failed chord grammar"
        )
        if resolution.suggestions:
            hit["candidate_kind"] = "uncertain_chord"
        rejects.append(hit)

    return dedupe_tokens(tokens), rejects, fragment_merges


def merge_fragment_hits(
    hits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int], list[dict[str, Any]]]:
    indexed = sorted(
        enumerate(hits),
        key=lambda item: (item[1]["bbox"][1], item[1]["bbox"][0]),
    )
    merged = []
    consumed: set[int] = set()
    merge_records = []

    for sorted_index, (left_original_index, left) in enumerate(indexed):
        if left_original_index in consumed:
            continue
        for right_original_index, right in (
            item for item in indexed[sorted_index + 1 :] if item[0] not in consumed
        ):
            candidate_text = merge_fragment_candidate(left, right)
            if candidate_text is None:
                continue
            score = min(float(left["score"]), float(right["score"]))
            bbox = union_bbox(left["bbox"], right["bbox"])
            merged_hit = {
                "text": candidate_text,
                "score": score,
                "bbox": list(bbox),
                "source": "paddle_hybrid_fragment_merge",
                "region_source": f"{left.get('region_source', '')}+{right.get('region_source', '')}",
                "system_index": left.get("system_index")
                if left.get("system_index") is not None
                else right.get("system_index"),
                "parts": [
                    compact_hit(left),
                    compact_hit(right),
                ],
                "merge_role": "root_suffix_merge",
            }
            merged.append(merged_hit)
            consumed.update({left_original_index, right_original_index})
            merge_records.append(
                {
                    "text": candidate_text,
                    "score": score,
                    "bbox": list(bbox),
                    "parts": [
                        compact_hit(left),
                        compact_hit(right),
                    ],
                }
            )
            break

    return merged, consumed, merge_records


def merge_fragment_candidate(left: dict[str, Any], right: dict[str, Any]) -> str | None:
    if not same_system(left, right):
        return None
    if vertical_overlap_ratio(left["bbox"], right["bbox"]) < 0.45:
        return None

    height = max(bbox_height(left["bbox"]), bbox_height(right["bbox"]), 1.0)
    gap = float(right["bbox"][0]) - float(left["bbox"][2])
    if gap < -(height * 0.35) or gap > max(34.0, height * 0.75):
        return None

    left_resolution = resolve_chord_ocr_text(str(left["text"]))
    if not left_resolution.accepted:
        return None
    left_norm = left_resolution.text_norm
    if not is_left_fragment_merge_base(left_norm):
        return None

    for right_text in candidate_suffix_texts(right):
        candidate = f"{left_norm}{right_text}"
        resolution = resolve_chord_ocr_text(candidate)
        if resolution.accepted and not root_only(resolution.text_norm):
            return resolution.text_norm

    return None


def candidate_suffix_texts(hit: dict[str, Any]) -> list[str]:
    values = [
        str(hit.get("text") or ""),
        str(hit.get("text_norm") or ""),
    ]
    result = []
    for value in values:
        cleaned = clean_suffix_fragment(value)
        if not cleaned or cleaned in result:
            continue
        if looks_like_suffix_fragment(cleaned):
            result.append(cleaned)
    return result


def clean_suffix_fragment(text: str) -> str:
    value = re.sub(r"\s+", "", text.strip())
    value = value.replace("_", "-")
    value = value.replace("o", "0") if value.isdigit() else value
    return value


def looks_like_suffix_fragment(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if lower[0].isdigit():
        return True
    if lower.startswith(("maj", "m", "-", "dim", "aug", "+", "sus", "add", "alt")):
        return True
    if lower[0] in {"b", "#"} and any(char.isdigit() for char in lower):
        return True
    return False


def build_hybrid_tokens(
    *,
    baseline_tokens: list[ChordToken],
    paddle_tokens: list[ChordToken],
    accepted_confidence_threshold: float,
    apply_replacements: bool = False,
) -> dict[str, Any]:
    hybrid_tokens = list(baseline_tokens)
    additions = []
    suppressed_additions = []
    duplicates = []
    replacement_candidates = []
    replacements_applied = []

    for paddle_token in sorted(paddle_tokens, key=lambda token: (token.bbox[1], token.bbox[0])):
        match_index = matching_token_index(paddle_token, hybrid_tokens)
        if match_index is None:
            if not safe_paddle_addition(paddle_token):
                suppressed_additions.append(serialize_token(paddle_token))
                continue
            hybrid_tokens.append(paddle_token)
            additions.append(serialize_token(paddle_token))
            continue

        baseline_token = hybrid_tokens[match_index]
        if paddle_token.text_norm == baseline_token.text_norm:
            duplicates.append(
                {
                    "baseline": serialize_token(baseline_token),
                    "paddle": serialize_token(paddle_token),
                }
            )
            continue

        candidate = {
            "baseline": serialize_token(baseline_token),
            "paddle": serialize_token(paddle_token),
            "overlap": round(bbox_overlap_ratio(baseline_token.bbox, paddle_token.bbox), 3),
        }
        replacement_candidates.append(candidate)
        if apply_replacements and should_apply_replacement(
            baseline_token=baseline_token,
            paddle_token=paddle_token,
            accepted_confidence_threshold=accepted_confidence_threshold,
        ):
            hybrid_tokens[match_index] = paddle_token
            replacements_applied.append(candidate)

    hybrid_tokens = dedupe_tokens(hybrid_tokens)
    hybrid_tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return {
        "tokens": hybrid_tokens,
        "additions": additions,
        "suppressed_additions": suppressed_additions,
        "duplicates": duplicates,
        "replacement_candidates": replacement_candidates,
        "replacements_applied": replacements_applied,
    }


def should_apply_replacement(
    *,
    baseline_token: ChordToken,
    paddle_token: ChordToken,
    accepted_confidence_threshold: float,
) -> bool:
    if root_only(paddle_token.text_norm):
        return False
    if high_risk_chord_text(paddle_token.text_norm):
        return False
    if chord_root(baseline_token.text_norm) != chord_root(paddle_token.text_norm):
        return False

    baseline_conf = baseline_token.confidence if baseline_token.confidence is not None else 1.0
    paddle_conf = paddle_token.confidence if paddle_token.confidence is not None else 0.0
    baseline_payload = serialize_token(baseline_token)
    baseline_is_high_risk = accepted_hit_needs_rescue(
        baseline_payload,
        accepted_confidence_threshold=accepted_confidence_threshold,
    )
    if not baseline_is_high_risk:
        return False
    if high_risk_chord_text(baseline_token.text_norm):
        return paddle_conf >= 0.15
    if baseline_conf <= accepted_confidence_threshold:
        return paddle_conf >= baseline_conf or paddle_conf >= 0.35
    if root_only(baseline_token.text_norm) and not root_only(paddle_token.text_norm):
        return True
    return False


def safe_paddle_addition(token: ChordToken) -> bool:
    if root_only(token.text_norm):
        return False
    if high_risk_chord_text(token.text_norm):
        return False
    return common_chord_text(token.text_norm)


def common_chord_text(text: str) -> bool:
    root = chord_root(text)
    if root is None:
        return False

    body = text[len(root) :]
    if not body:
        return False
    if "/" in body:
        chord_body, bass = body.split("/", 1)
        if chord_body not in _COMMON_ADDITION_SUFFIXES:
            return False
        return chord_root(bass) is not None
    return body in _COMMON_ADDITION_SUFFIXES


def chord_root(text: str) -> str | None:
    value = text.strip()
    if not value or value[0] not in _ROOTS:
        return None
    if len(value) > 1 and value[1] in {"b", "#"}:
        return value[:2]
    return value[0]


def dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for hit in sorted(hits, key=lambda item: (-float(item["score"]), item["bbox"][1], item["bbox"][0])):
        duplicate = False
        for current in deduped:
            if str(hit["text"]) != str(current["text"]):
                continue
            if bbox_iou(hit["bbox"], current["bbox"]) >= 0.50:
                duplicate = True
                break
            if centers_close(hit["bbox"], current["bbox"], tolerance=10.0):
                duplicate = True
                break
        if not duplicate:
            deduped.append(hit)
    deduped.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return deduped


def dedupe_tokens(tokens: list[ChordToken]) -> list[ChordToken]:
    deduped: list[ChordToken] = []
    for token in sorted(
        tokens,
        key=lambda item: (-(item.confidence or 0.0), item.bbox[1], item.bbox[0]),
    ):
        duplicate_index = matching_token_index(token, deduped)
        if duplicate_index is None:
            deduped.append(token)
            continue
        current = deduped[duplicate_index]
        if token.text_norm == current.text_norm and (token.confidence or 0.0) > (
            current.confidence or 0.0
        ):
            deduped[duplicate_index] = token
    deduped.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return deduped


def matching_token_index(token: ChordToken, candidates: list[ChordToken]) -> int | None:
    for index, current in enumerate(candidates):
        if bbox_iou(token.bbox, current.bbox) >= 0.35:
            return index
        if bbox_overlap_ratio(token.bbox, current.bbox) >= 0.55:
            return index
        if centers_close(token.bbox, current.bbox, tolerance=12.0):
            return index
    return None


def write_hybrid_overlay(
    *,
    image: Any,
    baseline_tokens: list[ChordToken],
    rescue_regions: list[RescueRegion],
    additions: list[dict[str, Any]],
    replacement_candidates: list[dict[str, Any]],
    replacements_applied: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    output_path: Path,
) -> None:
    overlay = image.copy()
    for token in baseline_tokens:
        draw_bbox_label(
            overlay,
            token.bbox,
            colour=(40, 180, 40),
            label=f"easy: {token.text_norm}",
            thickness=1,
        )
    for region in rescue_regions:
        draw_bbox_label(
            overlay,
            region.bbox,
            colour=(255, 170, 40),
            label="rescue",
            thickness=1,
        )
    for token in additions:
        draw_bbox_label(
            overlay,
            token.get("bbox"),
            colour=(220, 60, 220),
            label=f"add: {token.get('text_norm', '')}",
            thickness=2,
        )
    applied_keys = {
        json.dumps(item, sort_keys=True)
        for item in replacements_applied
    }
    for candidate in replacement_candidates:
        paddle = candidate.get("paddle") or {}
        applied = json.dumps(candidate, sort_keys=True) in applied_keys
        draw_bbox_label(
            overlay,
            paddle.get("bbox"),
            colour=(40, 210, 220) if applied else (80, 120, 230),
            label=f"{'replace' if applied else 'candidate'}: {paddle.get('text_norm', '')}",
            thickness=2,
        )
    for hit in rejected:
        draw_bbox_label(
            overlay,
            hit.get("bbox"),
            colour=(40, 40, 230),
            label=f"reject: {hit.get('text_norm') or hit.get('text') or ''}",
            thickness=1,
        )

    legend = [
        ("EasyOCR baseline", (40, 180, 40)),
        (f"Rescue regions: {len(rescue_regions)}", (255, 170, 40)),
        (f"Paddle additions: {len(additions)}", (220, 60, 220)),
        (f"Replacement candidates: {len(replacement_candidates)}", (80, 120, 230)),
        (f"Applied replacements: {len(replacements_applied)}", (40, 210, 220)),
        (f"Paddle rejects: {len(rejected)}", (40, 40, 230)),
    ]
    for index, (text, colour) in enumerate(legend):
        cv2.putText(
            overlay,
            text,
            (10, 24 + index * 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            colour,
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(output_path), overlay)


def draw_bbox_label(
    image: Any,
    bbox: Any,
    *,
    colour: tuple[int, int, int],
    label: str,
    thickness: int,
) -> None:
    box = coerce_payload_bbox(bbox)
    if box is None:
        return
    x0, y0, x1, y1 = [int(round(value)) for value in box]
    cv2.rectangle(image, (x0, y0), (x1, y1), colour, thickness)
    cv2.putText(
        image,
        truncate(label, limit=26),
        (x0, max(16, y0 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        colour,
        1,
        cv2.LINE_AA,
    )


def compact_trigger(payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "text": payload.get("text") or payload.get("text_raw"),
        "text_norm": payload.get("text_norm"),
        "conf": payload.get("conf"),
        "reason": payload.get("reason"),
        "candidate_kind": payload.get("candidate_kind"),
    }
    return {key: value for key, value in result.items() if value is not None}


def compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": hit.get("text"),
        "score": hit.get("score"),
        "bbox": hit.get("bbox"),
    }


def starts_with_chord_root(text: str) -> bool:
    value = text.strip()
    return bool(value) and value[0].upper() in _ROOTS


def high_risk_chord_text(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if value.count("(") != value.count(")"):
        return True

    root_end = 1
    if len(value) > 1 and value[1] in {"b", "#"}:
        root_end = 2
    body = value[root_end:]
    if body in {"19", "79", "69", "761", "769"}:
        return True
    if body.endswith(")") and "(" not in body:
        return True
    if body.endswith("1") and body not in {"11", "m11", "-11", "maj11"}:
        return True
    return False


def is_left_fragment_merge_base(text: str) -> bool:
    if root_only(text):
        return True
    if "/" in text:
        return True

    root_end = 1
    if len(text) > 1 and text[1] in {"b", "#"}:
        root_end = 2
    body = text[root_end:]
    return body in {"7", "9", "13"}


def root_only(text: str) -> bool:
    value = text.strip()
    if len(value) == 1:
        return value in _ROOTS
    return len(value) == 2 and value[0] in _ROOTS and value[1] in {"b", "#"}


def same_system(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_system = left.get("system_index")
    right_system = right.get("system_index")
    return left_system is None or right_system is None or left_system == right_system


def coerce_payload_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        return tuple(float(component) for component in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def coerce_paddle_box(
    value: Any,
    *,
    offset: tuple[int, int],
) -> tuple[float, float, float, float] | None:
    values = [float(component) for component in list(value)]
    if len(values) != 4:
        return None
    x0, y0, x1, y1 = values
    ox, oy = offset
    return (x0 + ox, y0 + oy, x1 + ox, y1 + oy)


def poly_to_bbox(value: Any, *, offset: tuple[int, int]) -> tuple[float, float, float, float]:
    points = value.tolist() if hasattr(value, "tolist") else value
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    ox, oy = offset
    return (min(xs) + ox, min(ys) + oy, max(xs) + ox, max(ys) + oy)


def coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def union_bbox(
    first: list[float] | tuple[float, float, float, float],
    second: list[float] | tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(float(first[0]), float(second[0])),
        min(float(first[1]), float(second[1])),
        max(float(first[2]), float(second[2])),
        max(float(first[3]), float(second[3])),
    )


def bbox_iou(first: Any, second: Any) -> float:
    first_box = coerce_payload_bbox(first)
    second_box = coerce_payload_bbox(second)
    if first_box is None or second_box is None:
        return 0.0
    intersection = intersection_area(first_box, second_box)
    if intersection <= 0:
        return 0.0
    first_area = bbox_area(first_box)
    second_area = bbox_area(second_box)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def bbox_overlap_ratio(first: Any, second: Any) -> float:
    first_box = coerce_payload_bbox(first)
    second_box = coerce_payload_bbox(second)
    if first_box is None or second_box is None:
        return 0.0
    intersection = intersection_area(first_box, second_box)
    denominator = min(bbox_area(first_box), bbox_area(second_box))
    return intersection / denominator if denominator > 0 else 0.0


def intersection_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return max(0.0, right - left) * max(0.0, bottom - top)


def bbox_area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def bbox_height(box: Any) -> float:
    value = coerce_payload_bbox(box)
    if value is None:
        return 0.0
    return max(0.0, value[3] - value[1])


def vertical_overlap_ratio(first: Any, second: Any) -> float:
    first_box = coerce_payload_bbox(first)
    second_box = coerce_payload_bbox(second)
    if first_box is None or second_box is None:
        return 0.0
    overlap = max(0.0, min(first_box[3], second_box[3]) - max(first_box[1], second_box[1]))
    denominator = min(first_box[3] - first_box[1], second_box[3] - second_box[1])
    return overlap / denominator if denominator > 0 else 0.0


def centers_close(first: Any, second: Any, *, tolerance: float) -> bool:
    first_box = coerce_payload_bbox(first)
    second_box = coerce_payload_bbox(second)
    if first_box is None or second_box is None:
        return False
    first_center = ((first_box[0] + first_box[2]) / 2.0, (first_box[1] + first_box[3]) / 2.0)
    second_center = (
        (second_box[0] + second_box[2]) / 2.0,
        (second_box[1] + second_box[3]) / 2.0,
    )
    return (
        abs(first_center[0] - second_center[0]) <= tolerance
        and abs(first_center[1] - second_center[1]) <= tolerance
    )


def truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}?"


if __name__ == "__main__":
    main()
