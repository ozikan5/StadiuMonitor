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

    people_source = (os.getenv("VIDEO_PEOPLE_SOURCE") or cfg.get("people_source", "yolo")).strip().lower()
    if people_source not in ("yolo", "motion", "density"):
        people_source = "yolo"

    yolo_model = os.getenv("VIDEO_YOLO_MODEL") or cfg.get("yolo_model", "yolov8n.pt")

    if os.getenv("VIDEO_YOLO_CONF") is not None:
        yolo_conf = float(os.environ["VIDEO_YOLO_CONF"])
    else:
        yolo_conf = float(cfg.get("yolo_conf", 0.15))

    if os.getenv("VIDEO_YOLO_MAX_WIDTH") is not None:
        yolo_max_width = int(os.environ["VIDEO_YOLO_MAX_WIDTH"])
    else:
        # 0 = do not shrink frame before inference (best for small/distant people; slower).
        yolo_max_width = int(cfg.get("yolo_max_width", 0))

    if os.getenv("VIDEO_YOLO_IMGSZ") is not None:
        yolo_imgsz = int(os.environ["VIDEO_YOLO_IMGSZ"])
    else:
        # Larger letterbox helps tiny pedestrians; 640 is faster but misses more at distance.
        yolo_imgsz = int(cfg.get("yolo_imgsz", 1280))

    yolo_device = (os.getenv("VIDEO_YOLO_DEVICE") or cfg.get("yolo_device", "auto")).strip().lower()

    if os.getenv("VIDEO_YOLO_TILE_GRID") is not None:
        yolo_tile_grid = int(os.environ["VIDEO_YOLO_TILE_GRID"])
    else:
        # 2 = 2x2 overlapping crops + NMS; helps wide shots. 1 = single full-frame pass (faster).
        yolo_tile_grid = int(cfg.get("yolo_tile_grid", 2))

    if os.getenv("VIDEO_YOLO_TILE_OVERLAP") is not None:
        yolo_tile_overlap = float(os.environ["VIDEO_YOLO_TILE_OVERLAP"])
    else:
        yolo_tile_overlap = float(cfg.get("yolo_tile_overlap", 0.25))

    if os.getenv("VIDEO_YOLO_TILE_NMS_IOU") is not None:
        yolo_tile_nms_iou = float(os.environ["VIDEO_YOLO_TILE_NMS_IOU"])
    else:
        yolo_tile_nms_iou = float(cfg.get("yolo_tile_nms_iou", 0.45))

    density_weights = (os.getenv("VIDEO_DENSITY_WEIGHTS") or cfg.get("density_weights") or "").strip()
    if os.getenv("VIDEO_DENSITY_MAX_SIDE") is not None:
        density_max_side = int(os.environ["VIDEO_DENSITY_MAX_SIDE"])
    else:
        density_max_side = int(cfg.get("density_max_side", 1280))
    density_gdrive_id = (os.getenv("VIDEO_DENSITY_GDRIVE_ID") or cfg.get("density_gdrive_id") or "").strip()

    if os.getenv("VIDEO_DENSITY_CALIBRATION") is not None:
        density_calibration = float(os.environ["VIDEO_DENSITY_CALIBRATION"])
    else:
        # Multiply raw sum(density); use >1 when eyeball count >> model (OOD video vs ShanghaiTech).
        density_calibration = float(cfg.get("density_calibration", 1.0))


    density_multi_scale = _env_bool("VIDEO_DENSITY_MULTI_SCALE", bool(cfg.get("density_multi_scale", False)))

    return {
        "camera_id": camera_id,
        "zone": zone,
        "priority": priority,
        "max_expected_occupancy": max_expected,
        "sample_fps": sample_fps,
        "motion_scale": motion_scale,
        "realtime": realtime,
        "loop": loop,
        "people_source": people_source,
        "yolo_model": yolo_model,
        "yolo_conf": yolo_conf,
        "yolo_max_width": yolo_max_width,
        "yolo_imgsz": yolo_imgsz,
        "yolo_device": yolo_device,
        "yolo_tile_grid": yolo_tile_grid,
        "yolo_tile_overlap": yolo_tile_overlap,
        "yolo_tile_nms_iou": yolo_tile_nms_iou,
        "density_weights": density_weights,
        "density_max_side": density_max_side,
        "density_gdrive_id": density_gdrive_id,
        "density_calibration": density_calibration,
        "density_multi_scale": density_multi_scale,
    }
