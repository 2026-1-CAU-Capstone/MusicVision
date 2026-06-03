from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.chords.models import ChordToken
from pipeline.chords.token_filters import serialize_token


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_SCRIPT = PROJECT_ROOT / "scripts" / "paddleocr_rescue_worker.py"


@dataclass(frozen=True)
class PaddleOCRRescueConfig:
    python_path: Path | None
    mode: str
    timeout_seconds: int
    cache_root: Path | None = None
    accepted_confidence_threshold: float = 0.50
    min_confidence: float = 0.15
    padding_x: int = 36
    padding_y: int = 28

    @property
    def enabled(self) -> bool:
        return self.mode in {"additions", "adjudicated"} and self.python_path is not None


def config_from_env() -> PaddleOCRRescueConfig:
    python_value = os.getenv("MUSICVISION_PADDLEOCR_PYTHON")
    mode = os.getenv("MUSICVISION_PADDLEOCR_RESCUE_MODE", "off").strip().lower()
    if mode in {"safe_additions", "safe-additions"}:
        mode = "additions"

    return PaddleOCRRescueConfig(
        python_path=Path(python_value) if python_value else None,
        mode=mode,
        timeout_seconds=_env_int("MUSICVISION_PADDLEOCR_TIMEOUT_SECONDS", 120),
        cache_root=(
            Path(cache_root)
            if (cache_root := os.getenv("MUSICVISION_PADDLEOCR_CACHE_ROOT"))
            else None
        ),
        accepted_confidence_threshold=_env_float(
            "MUSICVISION_PADDLEOCR_ACCEPTED_CONFIDENCE_THRESHOLD",
            0.50,
        ),
        min_confidence=_env_float("MUSICVISION_PADDLEOCR_MIN_CONFIDENCE", 0.15),
        padding_x=_env_int("MUSICVISION_PADDLEOCR_PADDING_X", 36),
        padding_y=_env_int("MUSICVISION_PADDLEOCR_PADDING_Y", 28),
    )


def maybe_apply_paddleocr_rescue(
    *,
    processed_image_path: Path,
    geometry: dict[str, Any],
    tokens: list[ChordToken],
    rejects: list[dict[str, Any]],
    output_dir: Path,
    config: PaddleOCRRescueConfig | None = None,
) -> tuple[list[ChordToken], list[dict[str, Any]], dict[str, Any] | None]:
    rescue_config = config if config is not None else config_from_env()
    if rescue_config.mode == "off":
        return tokens, rejects, None

    if rescue_config.mode not in {"additions", "adjudicated"}:
        return tokens, rejects, disabled_diagnostics(
            rescue_config,
            reason=f"unsupported_mode:{rescue_config.mode}",
        )

    if rescue_config.python_path is None:
        return tokens, rejects, disabled_diagnostics(
            rescue_config,
            reason="missing_musicvision_paddleocr_python",
        )

    if not rescue_config.python_path.exists():
        return tokens, rejects, disabled_diagnostics(
            rescue_config,
            reason="configured_python_not_found",
        )

    request_path = output_dir / "paddleocr_rescue_request.json"
    response_path = output_dir / "paddleocr_rescue_response.json"
    request_payload = {
        "image_path": str(processed_image_path),
        "geometry": geometry,
        "mode": rescue_config.mode,
        **(
            {"cache_root": str(rescue_config.cache_root)}
            if rescue_config.cache_root is not None
            else {}
        ),
        "baseline_diagnostics": {
            "accepted_tokens": [serialize_token(token) for token in tokens],
            "rejected_hits": rejects,
        },
        "params": {
            "accepted_confidence_threshold": rescue_config.accepted_confidence_threshold,
            "min_confidence": rescue_config.min_confidence,
            "padding_x": rescue_config.padding_x,
            "padding_y": rescue_config.padding_y,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request_payload, indent=2), encoding="utf-8")

    command = [
        str(rescue_config.python_path),
        str(WORKER_SCRIPT),
        "--request-json",
        str(request_path),
        "--response-json",
        str(response_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=rescue_config.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return tokens, rejects, disabled_diagnostics(
            rescue_config,
            reason="worker_timeout",
        )

    response = read_worker_response(response_path)
    if completed.returncode != 0 or response.get("status") != "completed":
        return tokens, rejects, {
            **disabled_diagnostics(rescue_config, reason="worker_failed"),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
            **({"error": response.get("error")} if response.get("error") else {}),
        }

    rescued_tokens = chord_tokens_from_payload(response.get("tokens") or [])
    diagnostics = response.get("diagnostics") or {}
    diagnostics.update(
        {
            "enabled": True,
            "worker": str(WORKER_SCRIPT).replace("\\", "/"),
            "mode": rescue_config.mode,
            "request_file": request_path.name,
            "response_file": response_path.name,
        }
    )
    combined_rejects = [*rejects, *(response.get("paddle_rejects") or [])]
    return rescued_tokens, combined_rejects, diagnostics


def disabled_diagnostics(
    config: PaddleOCRRescueConfig,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": config.mode,
        "reason": reason,
    }


def read_worker_response(response_path: Path) -> dict[str, Any]:
    if not response_path.exists():
        return {}
    try:
        return json.loads(response_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


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
                confidence=_coerce_float(value.get("conf")),
                system_index=_coerce_int(value.get("system_index")),
            )
        )
    return tokens


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
