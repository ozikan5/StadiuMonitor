"""
Load/save the camera registry (config/cameras.json).

Supports:
  - {"cameras": [ {...}, ... ]}  (preferred)
  - [ {...}, ... ]                (legacy array file)

Each camera may include optional `feed` (e.g. file path for video ingest) and `ingest` overrides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from shared.kafka_config import repo_root


def default_registry_path() -> Path:
    return repo_root() / "config" / "cameras.json"


def parse_registry_payload(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict) and "cameras" in data:
        raw = data["cameras"]
        if not isinstance(raw, list):
            raise ValueError('"cameras" must be a JSON array')
        return [c for c in raw if isinstance(c, dict)]
    if isinstance(data, dict):
        raise ValueError('cameras.json must be a JSON array or {"cameras": [...]}')
    raise ValueError("Invalid cameras.json root type")


def load_cameras(path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    p = Path(path) if path else default_registry_path()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_registry_payload(data)


def save_cameras(cameras: List[Dict[str, Any]], path: Optional[Path] = None) -> Path:
    p = path or default_registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cameras": cameras}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return p


def validate_camera(cam: Dict[str, Any]) -> None:
    if "camera_id" not in cam or not str(cam["camera_id"]).strip():
        raise ValueError("each camera needs non-empty camera_id")
    if "zone" not in cam or not str(cam["zone"]).strip():
        raise ValueError(f'camera {cam.get("camera_id")} needs zone')
