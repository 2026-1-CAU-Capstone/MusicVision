from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.chords.paddleocr_rescue import chord_tokens_from_payload
from pipeline.chords.paddleocr_rescue_overlay import write_paddleocr_rescue_overlay


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a PaddleOCR rescue overlay from saved worker request/response JSON.",
    )
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--response-json", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    request = json.loads(Path(args.request_json).read_text(encoding="utf-8-sig"))
    response = json.loads(Path(args.response_json).read_text(encoding="utf-8-sig"))
    diagnostics = response.get("diagnostics") or {}
    overlay_path = write_paddleocr_rescue_overlay(
        image_path=Path(str(request["image_path"])),
        output_dir=Path(args.output_dir),
        baseline_tokens=chord_tokens_from_payload(
            request.get("baseline_diagnostics", {}).get("accepted_tokens") or []
        ),
        diagnostics=diagnostics,
    )
    if overlay_path is None:
        raise SystemExit("Could not render PaddleOCR rescue overlay")
    print(str(overlay_path))


if __name__ == "__main__":
    main()
