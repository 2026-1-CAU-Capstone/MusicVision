from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2

from pipeline.chords.models import ChordToken


PADDLEOCR_RESCUE_OVERLAY_FILENAME = "paddleocr_rescue_overlay.png"

EASYOCR_BASELINE_COLOUR = (40, 180, 40)
RESCUE_REGION_COLOUR = (255, 170, 40)
PADDLE_ADDITION_COLOUR = (220, 60, 220)
REPLACEMENT_CANDIDATE_COLOUR = (80, 120, 230)
APPLIED_REPLACEMENT_COLOUR = (40, 210, 220)
PADDLE_REJECT_COLOUR = (40, 40, 230)
SUPPRESSED_ADDITION_COLOUR = (120, 120, 120)
FINAL_DECISION_COLOUR = (0, 0, 0)


def write_paddleocr_rescue_overlay(
    *,
    image_path: Path,
    output_dir: Path,
    baseline_tokens: list[ChordToken],
    diagnostics: dict[str, Any],
) -> Path | None:
    image = cv2.imread(str(image_path))
    if image is None:
        return None

    overlay = image.copy()
    for token in baseline_tokens:
        draw_bbox_label(
            overlay,
            token.bbox,
            colour=EASYOCR_BASELINE_COLOUR,
            label=f"easy: {token.text_norm}",
            thickness=1,
        )

    for region in diagnostics.get("rescue_regions") or []:
        draw_bbox_label(
            overlay,
            region.get("bbox"),
            colour=RESCUE_REGION_COLOUR,
            label="rescue",
            thickness=1,
        )

    for token in diagnostics.get("additions") or []:
        draw_bbox_label(
            overlay,
            token.get("bbox"),
            colour=PADDLE_ADDITION_COLOUR,
            label=f"add: {token.get('text_norm', '')}",
            thickness=2,
        )

    for token in diagnostics.get("suppressed_additions") or []:
        draw_bbox_label(
            overlay,
            token.get("bbox"),
            colour=SUPPRESSED_ADDITION_COLOUR,
            label=f"suppress: {token.get('text_norm', '')}",
            thickness=1,
        )

    applied_keys = applied_replacement_keys(diagnostics.get("candidate_groups") or [])
    for candidate in diagnostics.get("replacement_candidates") or []:
        paddle = candidate.get("paddle") or {}
        key = candidate_key(paddle)
        applied = key in applied_keys
        draw_bbox_label(
            overlay,
            paddle.get("bbox"),
            colour=APPLIED_REPLACEMENT_COLOUR
            if applied
            else REPLACEMENT_CANDIDATE_COLOUR,
            label=(
                f"{'replace' if applied else 'candidate'}: "
                f"{paddle.get('text_norm', '')}"
            ),
            thickness=2,
        )

    for hit in diagnostics.get("paddle_rejects") or []:
        draw_bbox_label(
            overlay,
            hit.get("bbox"),
            colour=PADDLE_REJECT_COLOUR,
            label=f"reject: {hit.get('text_norm') or hit.get('text') or ''}",
            thickness=1,
        )

    final_decisions = selected_decisions(diagnostics.get("candidate_groups") or [])
    for decision in final_decisions:
        draw_final_decision(
            overlay,
            decision,
        )

    legend = [
        ("EasyOCR baseline", EASYOCR_BASELINE_COLOUR),
        (
            f"Rescue regions: {len(diagnostics.get('rescue_regions') or [])}",
            RESCUE_REGION_COLOUR,
        ),
        (
            f"Paddle additions: {len(diagnostics.get('additions') or [])}",
            PADDLE_ADDITION_COLOUR,
        ),
        (
            f"Replacement candidates: {len(diagnostics.get('replacement_candidates') or [])}",
            REPLACEMENT_CANDIDATE_COLOUR,
        ),
        (
            f"Applied replacements: {len(diagnostics.get('replacements_applied') or [])}",
            APPLIED_REPLACEMENT_COLOUR,
        ),
        (
            f"Paddle rejects: {len(diagnostics.get('paddle_rejects') or [])}",
            PADDLE_REJECT_COLOUR,
        ),
        (
            f"Final decisions: {len(final_decisions)}",
            FINAL_DECISION_COLOUR,
        ),
    ]
    if diagnostics.get("suppressed_additions"):
        legend.append(
            (
                f"Suppressed additions: {len(diagnostics.get('suppressed_additions') or [])}",
                SUPPRESSED_ADDITION_COLOUR,
            )
        )

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

    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / PADDLEOCR_RESCUE_OVERLAY_FILENAME
    cv2.imwrite(str(overlay_path), overlay)
    return overlay_path


def applied_replacement_keys(candidate_groups: list[dict[str, Any]]) -> set[str]:
    keys = set()
    for group in candidate_groups:
        decision = group.get("decision") or {}
        if decision.get("selected_source") != "paddle_replacement_candidate":
            continue
        for candidate in group.get("candidates") or []:
            if candidate.get("source") != "paddle_replacement_candidate":
                continue
            if candidate.get("text_norm") != decision.get("selected_text_norm"):
                continue
            keys.add(candidate_key(candidate))
    return keys


def selected_decisions(candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = []
    for group in candidate_groups:
        decision = group.get("decision") or {}
        if decision.get("status") == "ignore":
            continue
        selected = selected_candidate(group)
        if selected is None:
            continue
        decisions.append(
            {
                "bbox": selected.get("bbox") or group.get("bbox"),
                "text_norm": decision.get("selected_text_norm"),
                "source": decision.get("selected_source"),
                "status": decision.get("status"),
                "reason": decision.get("reason"),
            }
        )
    return sorted(
        decisions,
        key=lambda item: (
            (rounded_bbox(item.get("bbox")) or [0.0, 0.0, 0.0, 0.0])[1],
            (rounded_bbox(item.get("bbox")) or [0.0, 0.0, 0.0, 0.0])[0],
        ),
    )


def selected_candidate(group: dict[str, Any]) -> dict[str, Any] | None:
    decision = group.get("decision") or {}
    selected_source = decision.get("selected_source")
    selected_text = decision.get("selected_text_norm")
    for candidate in group.get("candidates") or []:
        if candidate.get("source") != selected_source:
            continue
        if candidate.get("text_norm") != selected_text:
            continue
        return candidate
    return None


def draw_final_decision(
    image: Any,
    decision: dict[str, Any],
) -> None:
    box = rounded_bbox(decision.get("bbox"))
    if box is None:
        return
    x0, y0, x1, y1 = [int(round(value)) for value in box]
    pad = 5
    cv2.rectangle(
        image,
        (max(0, x0 - pad), max(0, y0 - pad)),
        (x1 + pad, y1 + pad),
        FINAL_DECISION_COLOUR,
        2,
    )

    label = f"FINAL: {decision.get('text_norm', '')}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.48
    thickness = 1
    (text_width, text_height), baseline = cv2.getTextSize(
        label,
        font,
        scale,
        thickness,
    )
    label_x = max(0, x0 - pad)
    label_y = max(text_height + 4, y0 - pad - 6)
    cv2.rectangle(
        image,
        (label_x, label_y - text_height - baseline - 4),
        (label_x + text_width + 8, label_y + baseline + 2),
        (255, 255, 255),
        -1,
    )
    cv2.rectangle(
        image,
        (label_x, label_y - text_height - baseline - 4),
        (label_x + text_width + 8, label_y + baseline + 2),
        FINAL_DECISION_COLOUR,
        1,
    )
    cv2.putText(
        image,
        label,
        (label_x + 4, label_y),
        font,
        scale,
        FINAL_DECISION_COLOUR,
        thickness,
        cv2.LINE_AA,
    )


def candidate_key(candidate: dict[str, Any]) -> str:
    return json.dumps(
        {
            "text_norm": candidate.get("text_norm"),
            "bbox": rounded_bbox(candidate.get("bbox")),
        },
        sort_keys=True,
    )


def rounded_bbox(bbox: Any) -> list[float] | None:
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    return [round(float(value), 1) for value in bbox]


def draw_bbox_label(
    image: Any,
    bbox: Any,
    *,
    colour: tuple[int, int, int],
    label: str,
    thickness: int,
) -> None:
    box = rounded_bbox(bbox)
    if box is None:
        return
    x0, y0, x1, y1 = [int(round(value)) for value in box]
    cv2.rectangle(image, (x0, y0), (x1, y1), colour, thickness)
    cv2.putText(
        image,
        truncate(label, limit=28),
        (x0, max(16, y0 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        colour,
        1,
        cv2.LINE_AA,
    )


def truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}?"
