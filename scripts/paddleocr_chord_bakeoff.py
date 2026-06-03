from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.chords.candidate_resolution import resolve_chord_ocr_text


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


@dataclass(frozen=True)
class OCRRegion:
    source: str
    system_index: int
    bbox: tuple[int, int, int, int]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a crop-level PaddleOCR bakeoff on saved HOMR chord bands.",
    )
    parser.add_argument(
        "--output-dir",
        default="storage/jobs/bench-paddleocr-chord-crops-20260604/output",
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
        help="Minimum OCR score before an otherwise valid chord is accepted.",
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
        summary = run_sample(
            sample_name=sample_name,
            sample_output_dir=sample_output_dir,
            output_dir=output_dir,
            ocr=ocr,
            min_confidence=args.min_confidence,
        )
        summaries.append(summary)

    payload = {
        "benchmark_type": "paddleocr_chord_crop_bakeoff",
        "pipeline": "saved_homr_chord_bands_paddleocr",
        "homr_rerun": False,
        "paddleocr_warmup_seconds": round(warmup_seconds, 3),
        "paddleocr_options": {
            "text_det_limit_side_len": args.text_det_limit_side_len,
            "text_det_limit_type": args.text_det_limit_type,
        },
        "samples": summaries,
        "notes": [
            "PaddleOCR ran on the same HOMR chord-band crop geometry used by targeted EasyOCR.",
            "Raw PaddleOCR hits were passed through the existing MusicVision chord resolver.",
            "This is an isolated bakeoff; PaddleOCR is not wired into production endpoints.",
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
) -> dict[str, Any]:
    processed_image_path = sample_output_dir / "homr_processed.png"
    geometry_path = sample_output_dir / "geometry.json"
    if not processed_image_path.exists() or not geometry_path.exists():
        raise FileNotFoundError(
            f"Missing saved HOMR artifacts for {sample_name}: {sample_output_dir}"
        )

    image = cv2.imread(str(processed_image_path))
    if image is None:
        raise RuntimeError(f"Could not read {processed_image_path}")
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    regions = chord_band_regions(image=image, geometry=geometry)

    started = time.perf_counter()
    hits: list[dict[str, Any]] = []
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        crop = image[y0:y1, x0:x1]
        for result in ocr.predict(crop):
            hits.extend(parse_result(result, offset=(x0, y0), region=region))
    elapsed = time.perf_counter() - started

    accepted = []
    rejected = []
    for hit in hits:
        resolution = resolve_chord_ocr_text(str(hit["text"]))
        hit["text_norm"] = resolution.text_norm
        hit["resolver_suggestions"] = resolution.suggestions
        hit["accepted_by_resolver"] = bool(resolution.accepted)
        if float(hit["score"]) >= min_confidence and resolution.accepted:
            accepted.append(hit)
        else:
            hit["reason"] = (
                f"confidence {hit['score']:.2f} < threshold {min_confidence:.2f}"
                if float(hit["score"]) < min_confidence
                else "failed chord grammar"
            )
            if resolution.suggestions:
                hit["candidate_kind"] = "uncertain_chord"
            rejected.append(hit)

    overlay_path = output_dir / f"{sample_name}_paddleocr_overlay.png"
    write_overlay(
        image=image,
        accepted=accepted,
        rejected=rejected,
        output_path=overlay_path,
    )

    sample_payload = {
        "sample": sample_name,
        "source_output_dir": str(sample_output_dir).replace("\\", "/"),
        "paddleocr_seconds": round(elapsed, 3),
        "regions": len(regions),
        "raw_hits": len(hits),
        "accepted_hits": len(accepted),
        "rejected_hits": len(rejected),
        "uncertain_rejected_hits": sum(
            1 for hit in rejected if hit.get("candidate_kind") == "uncertain_chord"
        ),
        "accepted": accepted,
        "rejected": rejected,
        "overlay_file": overlay_path.name,
    }
    (output_dir / f"{sample_name}.json").write_text(
        json.dumps(sample_payload, indent=2),
        encoding="utf-8",
    )
    return {
        key: value
        for key, value in sample_payload.items()
        if key not in {"accepted", "rejected"}
    }


def parse_result(
    result: Any,
    *,
    offset: tuple[int, int],
    region: OCRRegion,
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
            bbox = coerce_box(boxes[index], offset=offset)
        elif index < len(polys):
            bbox = poly_to_bbox(polys[index], offset=offset)
        if bbox is None:
            continue
        hits.append(
            {
                "text": str(text),
                "score": score,
                "bbox": list(bbox),
                "source": region.source,
                "system_index": region.system_index,
            }
        )
    return hits


def coerce_box(value: Any, *, offset: tuple[int, int]) -> tuple[float, float, float, float]:
    values = [float(component) for component in list(value)]
    if len(values) != 4:
        raise ValueError(f"Expected 4 box values, got {value!r}")
    x0, y0, x1, y1 = values
    ox, oy = offset
    return (x0 + ox, y0 + oy, x1 + ox, y1 + oy)


def poly_to_bbox(value: Any, *, offset: tuple[int, int]) -> tuple[float, float, float, float]:
    points = value.tolist() if hasattr(value, "tolist") else value
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    ox, oy = offset
    return (min(xs) + ox, min(ys) + oy, max(xs) + ox, max(ys) + oy)


def chord_band_regions(*, image: Any, geometry: dict[str, Any]) -> list[OCRRegion]:
    height, width = image.shape[:2]
    regions: list[OCRRegion] = []

    for system_index, bbox in usable_systems(geometry):
        x0, y0, x1, y1 = bbox
        system_height = max(1.0, y1 - y0)
        system_width = max(1.0, x1 - x0)
        x_margin = max(12.0, min(48.0, system_width * 0.04))
        top_margin = max(60.0, min(180.0, system_height * 1.45))
        staff_overlap = min(8.0, system_height * 0.08)

        crop_x0 = int(max(0, round(x0 - x_margin)))
        crop_x1 = int(min(width, round(x1 + x_margin)))
        crop_y0 = int(max(0, round(y0 - top_margin)))
        crop_y1 = int(min(height, round(y0 + staff_overlap)))

        if crop_x1 - crop_x0 < 24 or crop_y1 - crop_y0 < 20:
            continue
        regions.append(
            OCRRegion(
                source="paddle_targeted_chord_band",
                system_index=system_index,
                bbox=(crop_x0, crop_y0, crop_x1, crop_y1),
            )
        )

    return regions


def usable_systems(geometry: dict[str, Any]) -> list[tuple[int, tuple[float, float, float, float]]]:
    systems = []
    for raw_system in geometry.get("systems") or []:
        bbox = raw_system.get("bbox")
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        systems.append(
            (
                int(raw_system.get("index", len(systems) + 1)),
                tuple(float(component) for component in bbox),
            )
        )
    systems.sort(key=lambda item: ((item[1][1] + item[1][3]) / 2.0, item[1][0]))
    return systems


def write_overlay(
    *,
    image: Any,
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    output_path: Path,
) -> None:
    overlay = image.copy()
    draw_hits(overlay, accepted, colour=(40, 190, 40), prefix="paddle")
    draw_hits(overlay, rejected, colour=(40, 40, 230), prefix="reject")
    legend = f"Paddle accepted: {len(accepted)}  rejects: {len(rejected)}"
    cv2.putText(
        overlay,
        legend,
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (40, 190, 40),
        2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(output_path), overlay)


def draw_hits(image: Any, hits: list[dict[str, Any]], *, colour: tuple[int, int, int], prefix: str) -> None:
    for hit in hits:
        x0, y0, x1, y1 = [int(round(value)) for value in hit["bbox"]]
        cv2.rectangle(image, (x0, y0), (x1, y1), colour, 2)
        label = f"{prefix}: {hit['text']} -> {hit.get('text_norm', '')}"
        cv2.putText(
            image,
            label,
            (x0, max(16, y0 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            colour,
            1,
            cv2.LINE_AA,
        )


if __name__ == "__main__":
    main()
