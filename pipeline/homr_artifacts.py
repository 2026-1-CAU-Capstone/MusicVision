from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HomrArtifactPaths:
    musicxml_path: Path
    geometry_json_path: Path
    processed_image_path: Path


def load_geometry_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
