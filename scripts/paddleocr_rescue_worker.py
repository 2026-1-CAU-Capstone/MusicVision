from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.chords.models import ChordToken
from pipeline.chords.token_filters import serialize_token
from scripts.chord_candidate_adjudication import (
    build_candidate_groups,
    candidate_from_token,
    decide_group,
    serialize_group,
)
from scripts.paddleocr_hybrid_chord_rescue import (
    build_hybrid_tokens,
    build_rescue_regions,
    configure_paddle_environment,
    dedupe_hits,
    parse_result,
    resolve_paddle_hits,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Isolated PaddleOCR chord rescue worker for MusicVision.",
    )
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--response-json", required=True)
    args = parser.parse_args()

    request_path = Path(args.request_json)
    response_path = Path(args.response_json)
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))

    try:
        response = run_rescue(request)
    except Exception as exc:  # pragma: no cover - exercised by parent fallback
        response = {
            "status": "failed",
            "error": str(exc),
        }

    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response, indent=2), encoding="utf-8")
    if response.get("status") != "completed":
        raise SystemExit(1)


def run_rescue(request: dict[str, Any]) -> dict[str, Any]:
    configure_paddle_environment(
        Path(
            request.get("cache_root")
            or Path(os.environ.get("TEMP", ".")) / "musicvision-paddle-home"
        )
    )

    from paddleocr import PaddleOCR

    image_path = Path(str(request["image_path"]))
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")

    baseline_diagnostics = request.get("baseline_diagnostics") or {}
    params = request.get("params") or {}
    mode = str(request.get("mode") or "additions").strip().lower()
    if mode not in {"additions", "adjudicated"}:
        raise ValueError(f"Unsupported rescue mode: {mode}")

    started = time.perf_counter()
    ocr = PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        text_det_limit_side_len=params.get("text_det_limit_side_len"),
        text_det_limit_type=params.get("text_det_limit_type"),
    )
    warmup_seconds = time.perf_counter() - started

    regions = build_rescue_regions(
        image_shape=image.shape,
        baseline_diagnostics=baseline_diagnostics,
        accepted_confidence_threshold=float(
            params.get("accepted_confidence_threshold", 0.50)
        ),
        padding_x=int(params.get("padding_x", 36)),
        padding_y=int(params.get("padding_y", 28)),
    )

    started = time.perf_counter()
    raw_hits: list[dict[str, Any]] = []
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        crop = image[y0:y1, x0:x1]
        for result in ocr.predict(crop):
            raw_hits.extend(parse_result(result, offset=(x0, y0), region=region))
    elapsed = time.perf_counter() - started

    raw_hits = dedupe_hits(raw_hits)
    paddle_tokens, paddle_rejects, fragment_merges = resolve_paddle_hits(
        raw_hits,
        min_confidence=float(params.get("min_confidence", 0.15)),
    )
    baseline_tokens = chord_tokens_from_payload(
        baseline_diagnostics.get("accepted_tokens") or []
    )
    hybrid = build_hybrid_tokens(
        baseline_tokens=baseline_tokens,
        paddle_tokens=paddle_tokens,
        accepted_confidence_threshold=float(
            params.get("accepted_confidence_threshold", 0.50)
        ),
        apply_replacements=False,
    )

    if mode == "adjudicated":
        final_tokens, candidate_groups = adjudicate_tokens(
            baseline_tokens=baseline_tokens,
            additions=hybrid["additions"],
            replacement_candidates=hybrid["replacement_candidates"],
            suppressed_additions=hybrid["suppressed_additions"],
        )
    else:
        final_tokens = hybrid["tokens"]
        candidate_groups = []

    final_tokens.sort(key=lambda token: (token.bbox[1], token.bbox[0]))
    return {
        "status": "completed",
        "mode": mode,
        "tokens": [serialize_token(token) for token in final_tokens],
        "paddle_rejects": paddle_rejects,
        "diagnostics": {
            "mode": mode,
            "regions": len(regions),
            "seconds": round(elapsed, 3),
            "warmup_seconds": round(warmup_seconds, 3),
            "raw_hits": len(raw_hits),
            "accepted_hits": len(paddle_tokens),
            "rejected_hits": len(paddle_rejects),
            "fragment_merges": len(fragment_merges),
            "duplicate_hits": len(hybrid["duplicates"]),
            "additions": hybrid["additions"],
            "suppressed_additions": hybrid["suppressed_additions"],
            "replacement_candidates": hybrid["replacement_candidates"],
            "replacements_applied": replacement_decisions(candidate_groups),
            "candidate_groups": candidate_groups,
        },
    }


def adjudicate_tokens(
    *,
    baseline_tokens: list[ChordToken],
    additions: list[dict[str, Any]],
    replacement_candidates: list[dict[str, Any]],
    suppressed_additions: list[dict[str, Any]],
) -> tuple[list[ChordToken], list[dict[str, Any]]]:
    groups = build_candidate_groups(
        sample_name="production",
        baseline_tokens=[
            candidate_from_token(
                serialize_token(token),
                source="easyocr_baseline",
                current_hybrid_applied=True,
                eligible=True,
            )
            for token in baseline_tokens
        ],
        additions=additions,
        replacement_candidates=replacement_candidates,
        suppressed_additions=suppressed_additions,
    )
    decisions = [decide_group(group) for group in groups]
    serialized_groups = [
        serialize_group(group=group, decision=decision)
        for group, decision in zip(groups, decisions, strict=True)
    ]

    tokens = []
    for group, decision in zip(groups, decisions, strict=True):
        if decision["status"] == "ignore":
            continue
        selected = find_selected_candidate(group.candidates, decision)
        if selected is None:
            continue
        tokens.append(
            ChordToken(
                text_raw=selected.text_raw,
                text_norm=selected.text_norm,
                bbox=selected.bbox,
                confidence=selected.confidence,
                system_index=selected.system_index,
            )
        )
    return tokens, serialized_groups


def replacement_decisions(candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacements = []
    for group in candidate_groups:
        decision = group.get("decision") or {}
        if decision.get("selected_source") != "paddle_replacement_candidate":
            continue
        replacements.append(
            {
                "group_id": group.get("group_id"),
                "text_raw": decision.get("selected_text_raw"),
                "text_norm": decision.get("selected_text_norm"),
                "reason": decision.get("reason"),
            }
        )
    return replacements


def find_selected_candidate(candidates: list[Any], decision: dict[str, Any]) -> Any | None:
    for candidate in candidates:
        if candidate.source != decision["selected_source"]:
            continue
        if candidate.text_norm != decision["selected_text_norm"]:
            continue
        return candidate
    return None


def chord_tokens_from_payload(values: list[dict[str, Any]]) -> list[ChordToken]:
    tokens = []
    for value in values:
        bbox = value.get("bbox")
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        tokens.append(
            ChordToken(
                text_raw=str(value.get("text_raw") or value.get("text") or ""),
                text_norm=str(value.get("text_norm") or ""),
                bbox=tuple(float(component) for component in bbox),
                confidence=coerce_float(value.get("conf")),
                system_index=coerce_int(value.get("system_index")),
            )
        )
    return tokens


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


if __name__ == "__main__":
    main()
