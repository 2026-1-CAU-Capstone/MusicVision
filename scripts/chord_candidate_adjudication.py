from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.paddleocr_hybrid_chord_rescue import (
    bbox_iou,
    bbox_overlap_ratio,
    centers_close,
    chord_root,
    common_chord_text,
    coerce_payload_bbox,
    high_risk_chord_text,
    root_only,
)


DEFAULT_HYBRID_OUTPUT_DIR = Path(
    "storage/jobs/bench-paddleocr-hybrid-rescue-20260604/output"
)
DEFAULT_OUTPUT_DIR = Path(
    "storage/jobs/bench-chord-candidate-adjudication-20260604/output"
)


@dataclass(frozen=True)
class Candidate:
    source: str
    text_raw: str
    text_norm: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    current_hybrid_applied: bool
    eligible: bool = True
    system_index: int | None = None

    @property
    def root(self) -> str | None:
        return chord_root(self.text_norm)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "text_raw": self.text_raw,
            "text_norm": self.text_norm,
            "bbox": list(self.bbox),
            "current_hybrid_applied": self.current_hybrid_applied,
            "eligible": self.eligible,
            "is_common": common_chord_text(self.text_norm),
            "is_high_risk": high_risk_chord_text(self.text_norm),
        }
        if self.confidence is not None:
            payload["conf"] = self.confidence
        if self.system_index is not None:
            payload["system_index"] = self.system_index
        if self.root is not None:
            payload["root"] = self.root
        return payload


@dataclass
class CandidateGroup:
    group_id: str
    candidates: list[Candidate]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [candidate.bbox for candidate in self.candidates]
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    def add(self, candidate: Candidate) -> None:
        if any(same_candidate(candidate, current) for current in self.candidates):
            return
        self.candidates.append(candidate)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Group EasyOCR/PaddleOCR chord candidates by physical location and "
            "emit a first-pass adjudicated winner for each group."
        ),
    )
    parser.add_argument(
        "--hybrid-output-dir",
        default=str(DEFAULT_HYBRID_OUTPUT_DIR),
        help="Directory containing Paddle hybrid rescue sample JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where adjudication JSON/CSV files are written.",
    )
    args = parser.parse_args()

    hybrid_output_dir = Path(args.hybrid_output_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sample_summaries = []
    for sample_path in sorted(hybrid_output_dir.glob("*.json")):
        if sample_path.name == "summary.json":
            continue
        sample_summaries.append(run_sample(sample_path=sample_path, output_dir=output_dir))

    summary = {
        "benchmark_type": "chord_candidate_adjudication",
        "source_hybrid_output_dir": str(hybrid_output_dir).replace("\\", "/"),
        "samples": sample_summaries,
        "notes": [
            "This does not rerun OCR. It groups saved EasyOCR baseline, Paddle additions, and Paddle replacement candidates.",
            "Green EasyOCR baseline and magenta Paddle additions are already applied by the current hybrid run.",
            "Orange replacement candidates are selected only when conservative local evidence is strong; otherwise they remain review candidates.",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


def run_sample(*, sample_path: Path, output_dir: Path) -> dict[str, Any]:
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    sample_name = str(payload["sample"])
    baseline_tokens = load_baseline_tokens(payload)
    groups = build_candidate_groups(
        sample_name=sample_name,
        baseline_tokens=baseline_tokens,
        additions=payload.get("additions") or [],
        replacement_candidates=payload.get("replacement_candidates") or [],
        suppressed_additions=payload.get("suppressed_additions") or [],
    )

    decisions = [decide_group(group) for group in groups]
    group_payloads = [
        serialize_group(group=group, decision=decision)
        for group, decision in zip(groups, decisions, strict=True)
    ]
    group_payloads.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))

    json_path = output_dir / f"{sample_name}_candidate_groups.json"
    csv_path = output_dir / f"{sample_name}_candidate_groups.csv"
    json_path.write_text(json.dumps(group_payloads, indent=2), encoding="utf-8")
    write_groups_csv(csv_path, group_payloads)

    summary = summarize_sample(
        sample_name=sample_name,
        groups=group_payloads,
        baseline_count=len(baseline_tokens),
        additions_count=len(payload.get("additions") or []),
        replacement_count=len(payload.get("replacement_candidates") or []),
    )
    summary["groups_file"] = json_path.name
    summary["review_csv"] = csv_path.name
    return summary


def load_baseline_tokens(payload: dict[str, Any]) -> list[Candidate]:
    source_output_dir = Path(str(payload["source_output_dir"]))
    baseline_path = source_output_dir / "chord_assignments.json"
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    return [
        candidate_from_token(
            token,
            source="easyocr_baseline",
            current_hybrid_applied=True,
            eligible=True,
        )
        for token in baseline_payload.get("chord_ocr", {}).get("accepted_tokens") or []
        if coerce_payload_bbox(token.get("bbox")) is not None
    ]


def build_candidate_groups(
    *,
    sample_name: str,
    baseline_tokens: list[Candidate],
    additions: list[dict[str, Any]],
    replacement_candidates: list[dict[str, Any]],
    suppressed_additions: list[dict[str, Any]],
) -> list[CandidateGroup]:
    groups: list[CandidateGroup] = []

    for baseline in baseline_tokens:
        add_candidate_to_groups(sample_name=sample_name, candidate=baseline, groups=groups)

    for addition in additions:
        add_candidate_to_groups(
            sample_name=sample_name,
            candidate=candidate_from_token(
                addition,
                source="paddle_addition",
                current_hybrid_applied=True,
                eligible=True,
            ),
            groups=groups,
        )

    for suppressed in suppressed_additions:
        add_candidate_to_groups(
            sample_name=sample_name,
            candidate=candidate_from_token(
                suppressed,
                source="paddle_suppressed_addition",
                current_hybrid_applied=False,
                eligible=False,
            ),
            groups=groups,
        )

    for replacement in replacement_candidates:
        baseline = candidate_from_token(
            replacement["baseline"],
            source="easyocr_baseline",
            current_hybrid_applied=True,
            eligible=True,
        )
        paddle = candidate_from_token(
            replacement["paddle"],
            source="paddle_replacement_candidate",
            current_hybrid_applied=False,
            eligible=True,
        )
        add_candidate_to_groups(sample_name=sample_name, candidate=baseline, groups=groups)
        add_candidate_to_groups(sample_name=sample_name, candidate=paddle, groups=groups)

    groups.sort(key=lambda group: (group.bbox[1], group.bbox[0]))
    for index, group in enumerate(groups, start=1):
        group.group_id = f"{sample_name}-{index:03d}"
    return groups


def add_candidate_to_groups(
    *,
    sample_name: str,
    candidate: Candidate,
    groups: list[CandidateGroup],
) -> None:
    match = matching_group_index(candidate, groups)
    if match is not None:
        groups[match].add(candidate)
        return

    groups.append(
        CandidateGroup(
            group_id=f"{sample_name}-{len(groups) + 1:03d}",
            candidates=[candidate],
        )
    )


def matching_group_index(candidate: Candidate, groups: list[CandidateGroup]) -> int | None:
    for index, group in enumerate(groups):
        if bbox_iou(candidate.bbox, group.bbox) >= 0.35:
            return index
        if bbox_overlap_ratio(candidate.bbox, group.bbox) >= 0.55:
            return index
        if centers_close(candidate.bbox, group.bbox, tolerance=14.0):
            return index
    return None


def decide_group(group: CandidateGroup) -> dict[str, Any]:
    candidates = group.candidates
    baseline = first_source(candidates, "easyocr_baseline")
    additions = [candidate for candidate in candidates if candidate.source == "paddle_addition"]
    replacements = [
        candidate
        for candidate in candidates
        if candidate.source == "paddle_replacement_candidate"
    ]

    if additions and baseline is None:
        winner = max(additions, key=lambda candidate: candidate.confidence or 0.0)
        return decision_payload(
            winner=winner,
            status="auto",
            reason="safe_paddle_addition_without_easyocr_overlap",
        )

    if baseline is None:
        eligible = [candidate for candidate in candidates if candidate.eligible]
        if not eligible:
            winner = max(candidates, key=lambda candidate: candidate.confidence or 0.0)
            return decision_payload(
                winner=winner,
                status="ignore",
                reason="no_eligible_candidate_in_group",
            )
        winner = max(eligible, key=lambda candidate: candidate.confidence or 0.0)
        return decision_payload(
            winner=winner,
            status="review",
            reason="no_easyocr_baseline_for_candidate_group",
        )

    if not replacements:
        return decision_payload(
            winner=baseline,
            status="auto",
            reason="easyocr_baseline_only",
        )

    replacement_decisions = [
        replacement_evidence(baseline=baseline, paddle=candidate)
        for candidate in replacements
    ]
    auto_candidates = [
        item
        for item in replacement_decisions
        if item["status"] == "auto_replace"
    ]
    if len(auto_candidates) == 1:
        return decision_payload(
            winner=auto_candidates[0]["candidate"],
            status="auto",
            reason=auto_candidates[0]["reason"],
            evidence=strip_candidate_objects(replacement_decisions),
        )

    review_candidates = [
        item
        for item in replacement_decisions
        if item["status"] in {"auto_replace", "review_replace"}
    ]
    if review_candidates:
        return decision_payload(
            winner=baseline,
            status="review",
            reason="replacement_candidate_needs_review",
            evidence=strip_candidate_objects(replacement_decisions),
        )

    return decision_payload(
        winner=baseline,
        status="auto",
        reason="replacement_candidate_rejected_by_local_evidence",
        evidence=strip_candidate_objects(replacement_decisions),
    )


def replacement_evidence(*, baseline: Candidate, paddle: Candidate) -> dict[str, Any]:
    if not paddle.eligible:
        return {
            "candidate": paddle,
            "status": "reject_replace",
            "reason": "candidate_not_eligible",
        }
    if root_only(paddle.text_norm):
        return {
            "candidate": paddle,
            "status": "reject_replace",
            "reason": "paddle_candidate_is_root_only",
        }
    if high_risk_chord_text(paddle.text_norm) or not common_chord_text(paddle.text_norm):
        return {
            "candidate": paddle,
            "status": "reject_replace",
            "reason": "paddle_candidate_not_common_safe_shape",
        }

    relation = root_relation(baseline.text_norm, paddle.text_norm)
    baseline_suspicious = suspicious_baseline(baseline)
    if relation in {"same_root", "same_letter_accidental"} and baseline_suspicious:
        return {
            "candidate": paddle,
            "status": "auto_replace",
            "reason": f"{relation}_paddle_candidate_for_suspicious_baseline",
            "baseline_suspicious": baseline_suspicious,
            "root_relation": relation,
        }

    if relation in {"same_root", "same_letter_accidental"}:
        return {
            "candidate": paddle,
            "status": "review_replace",
            "reason": f"{relation}_paddle_candidate_for_plausible_baseline",
            "baseline_suspicious": baseline_suspicious,
            "root_relation": relation,
        }

    return {
        "candidate": paddle,
        "status": "review_replace",
        "reason": "different_root_candidate",
        "baseline_suspicious": baseline_suspicious,
        "root_relation": relation,
    }


def suspicious_baseline(candidate: Candidate) -> bool:
    if high_risk_chord_text(candidate.text_norm):
        return True
    if not common_chord_text(candidate.text_norm):
        return True
    return (candidate.confidence or 1.0) <= 0.30


def root_relation(left: str, right: str) -> str:
    left_root = chord_root(left)
    right_root = chord_root(right)
    if left_root is None or right_root is None:
        return "missing_root"
    if left_root == right_root:
        return "same_root"
    if left_root[0] == right_root[0]:
        return "same_letter_accidental"
    return "different_root"


def decision_payload(
    *,
    winner: Candidate,
    status: str,
    reason: str,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "selected_source": winner.source,
        "selected_text_raw": winner.text_raw,
        "selected_text_norm": winner.text_norm,
        "selected_conf": winner.confidence,
        "status": status,
        "reason": reason,
        **({"replacement_evidence": evidence} if evidence is not None else {}),
    }


def strip_candidate_objects(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped = []
    for value in values:
        candidate = value["candidate"]
        stripped.append(
            {
                key: item
                for key, item in value.items()
                if key != "candidate"
            }
            | {
                "candidate": candidate.to_dict(),
            }
        )
    return stripped


def serialize_group(
    *,
    group: CandidateGroup,
    decision: dict[str, Any],
) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "bbox": list(group.bbox),
        "decision": decision,
        "candidate_count": len(group.candidates),
        "sources": sorted({candidate.source for candidate in group.candidates}),
        "candidates": [candidate.to_dict() for candidate in group.candidates],
    }


def summarize_sample(
    *,
    sample_name: str,
    groups: list[dict[str, Any]],
    baseline_count: int,
    additions_count: int,
    replacement_count: int,
) -> dict[str, Any]:
    selected_sources = [group["decision"]["selected_source"] for group in groups]
    applied_sources = [
        group["decision"]["selected_source"]
        for group in groups
        if group["decision"]["status"] != "ignore"
    ]
    statuses = [group["decision"]["status"] for group in groups]
    reasons = [group["decision"]["reason"] for group in groups]
    return {
        "sample": sample_name,
        "groups": len(groups),
        "source_counts": {
            "easyocr_baseline": baseline_count,
            "paddle_addition": additions_count,
            "paddle_replacement_candidate": replacement_count,
        },
        "selected_counts": count_values(selected_sources),
        "applied_counts": count_values(applied_sources),
        "status_counts": count_values(statuses),
        "reason_counts": count_values(reasons),
        "multi_candidate_groups": sum(1 for group in groups if group["candidate_count"] > 1),
        "review_groups": sum(1 for group in groups if group["decision"]["status"] == "review"),
        "ignored_groups": sum(1 for group in groups if group["decision"]["status"] == "ignore"),
    }


def write_groups_csv(path: Path, groups: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "group_id",
                "selected_text_norm",
                "selected_source",
                "status",
                "reason",
                "candidates",
                "bbox",
            ],
        )
        writer.writeheader()
        for group in groups:
            writer.writerow(
                {
                    "group_id": group["group_id"],
                    "selected_text_norm": group["decision"]["selected_text_norm"],
                    "selected_source": group["decision"]["selected_source"],
                    "status": group["decision"]["status"],
                    "reason": group["decision"]["reason"],
                    "candidates": " | ".join(
                        f"{candidate['source']}:{candidate['text_norm']}"
                        for candidate in group["candidates"]
                    ),
                    "bbox": json.dumps(group["bbox"]),
                }
            )


def candidate_from_token(
    token: dict[str, Any],
    *,
    source: str,
    current_hybrid_applied: bool,
    eligible: bool,
) -> Candidate:
    bbox = coerce_payload_bbox(token.get("bbox"))
    if bbox is None:
        raise ValueError(f"Missing candidate bbox: {token!r}")
    return Candidate(
        source=source,
        text_raw=str(token.get("text_raw") or token.get("text") or ""),
        text_norm=str(token.get("text_norm") or ""),
        bbox=bbox,
        confidence=coerce_float(token.get("conf")),
        current_hybrid_applied=current_hybrid_applied,
        eligible=eligible,
        system_index=coerce_int(token.get("system_index")),
    )


def first_source(candidates: list[Candidate], source: str) -> Candidate | None:
    return next((candidate for candidate in candidates if candidate.source == source), None)


def same_candidate(first: Candidate, second: Candidate) -> bool:
    return (
        first.source == second.source
        and first.text_norm == second.text_norm
        and bbox_overlap_ratio(first.bbox, second.bbox) >= 0.85
    )


def count_values(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


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
