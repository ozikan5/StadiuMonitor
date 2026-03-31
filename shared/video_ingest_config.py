"""
Defaults for video_ingest (one logical camera): zone, caps, pacing.

Kafka broker/topic stay in config/kafka.example.json — different concern.

Precedence: environment variables, then config file, then code defaults.
Files: config/video_ingest.json (gitignored), else config/video_ingest.example.json.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from shared.kafka_config import repo_root


def load_video_ingest_config() -> Dict[str, Any]:
    root = repo_root()
    for name in ("video_ingest.json", "video_ingest.example.json"):
        path = root / "config" / name
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def _env_bool(name: str, fallback: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    return raw.lower() in ("1", "true", "yes", "on")


def video_ingest_settings() -> Dict[str, Any]:
    cfg = load_video_ingest_config()

    camera_id = os.getenv("VIDEO_CAMERA_ID") or cfg.get("camera_id", "CAM-VIDEO-001")
    zone = os.getenv("VIDEO_ZONE") or cfg.get("zone", "sample-feed")
    priority = os.getenv("VIDEO_PRIORITY") or cfg.get("priority", "medium")

    if os.getenv("VIDEO_MAX_OCCUPANCY") is not None:
        max_expected = int(os.environ["VIDEO_MAX_OCCUPANCY"])
    else:
        max_expected = int(cfg.get("max_expected_occupancy", 220))

    if os.getenv("VIDEO_SAMPLE_FPS") is not None:
        sample_fps = float(os.environ["VIDEO_SAMPLE_FPS"])
    else:
        sample_fps = float(cfg.get("sample_fps", 2))

    if os.getenv("VIDEO_MOTION_SCALE") is not None:
        motion_scale = float(os.environ["VIDEO_MOTION_SCALE"])
    else:
        motion_scale = float(cfg.get("motion_scale", 6.0))

    realtime = _env_bool("VIDEO_REALTIME", bool(cfg.get("realtime", True)))
    loop = _env_bool("VIDEO_LOOP", bool(cfg.get("loop", False)))

    return {
        "camera_id": camera_id,
        "zone": zone,
        "priority": priority,
        "max_expected_occupancy": max_expected,
        "sample_fps": sample_fps,
        "motion_scale": motion_scale,
        "realtime": realtime,
        "loop": loop,
    }
