"""
Video file → Kafka with the same event shape as the random simulator.

people_source=yolo (default): YOLOv8 person boxes (+ optional tiling).
people_source=density: CSRNet crowd density map (sum ≈ count; better for dense crowds, domain-biased).
people_source=motion: cheap pixel-diff proxy (no heavy ML).

On Apple Silicon, device=auto prefers MPS; falls back to CPU.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
from kafka import KafkaProducer

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from shared.kafka_config import kafka_settings
from shared.video_ingest_config import video_ingest_settings

from yolo_counter import count_people, load_yolo, resolve_device

_CONF_DENSITY = 0.75

RUNNING = True


def stop_handler(signum, frame):
    del signum, frame
    global RUNNING
    RUNNING = False


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_sample_video() -> Optional[Path]:
    samples = project_root() / "data" / "samples"
    if not samples.is_dir():
        return None
    mp4s = sorted(samples.glob("*.mp4"))
    return mp4s[0] if mp4s else None


def build_producer(bootstrap_servers: str, linger_ms: int) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        linger_ms=linger_ms,
    )


def motion_score(prev_gray, gray) -> float:
    diff = cv2.absdiff(prev_gray, gray)
    return float(cv2.mean(diff)[0])


def score_to_people_count(score: float, scale: float, max_occ: int) -> int:
    raw = int(score * scale)
    return max(0, min(raw, max_occ + 75))


def media_time_seconds(cap: cv2.VideoCapture, frame_index: int, fps: float) -> float:
    """Seconds from the start of the file for the current frame (best effort)."""
    msec = cap.get(cv2.CAP_PROP_POS_MSEC)
    if msec is not None and float(msec) > 0:
        return float(msec) / 1000.0
    return max(0.0, (frame_index - 1) / max(fps, 1e-6))


def format_media_timecode(seconds: float) -> str:
    """HH:MM:SS.mmm for correlating with players and scrubbers."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    s, ms = divmod(total_ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def make_event(
    *,
    camera_id: str,
    zone: str,
    priority: str,
    max_occ: int,
    people_count: int,
    confidence: float,
    ingest_mode: str,
) -> Dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_id": camera_id,
        "zone": zone,
        "priority": priority,
        "people_count": people_count,
        "max_expected_occupancy": max_occ,
        "estimated_queue_length": max(0, people_count - int(max_occ * 0.8)),
        "detection_confidence": round(confidence, 3),
        "ingest_mode": ingest_mode,
    }


def parse_args() -> argparse.Namespace:
    ks = kafka_settings()
    vi = video_ingest_settings()
    p = argparse.ArgumentParser(description="Video file → Kafka (stadium camera-shaped events)")
    p.add_argument(
        "--video",
        default=os.getenv("VIDEO_PATH", ""),
        help="Path to MP4 (default: first *.mp4 under data/samples/)",
    )
    p.add_argument("--bootstrap-servers", default=ks["bootstrap_servers"])
    p.add_argument("--topic", default=ks["topic"])
    p.add_argument(
        "--producer-linger-ms",
        type=int,
        default=ks["producer_linger_ms"],
        help="Kafka producer linger_ms (config/kafka.example.json or env)",
    )
    p.add_argument("--camera-id", default=vi["camera_id"])
    p.add_argument("--zone", default=vi["zone"])
    p.add_argument("--priority", default=vi["priority"])
    p.add_argument(
        "--max-expected-occupancy",
        type=int,
        default=vi["max_expected_occupancy"],
        help="Cap used for alerts and scaling; see config/video_ingest.example.json",
    )
    p.add_argument(
        "--sample-fps",
        type=float,
        default=vi["sample_fps"],
        help="Target Kafka messages per second of *video timeline* (uses stride across frames)",
    )
    p.add_argument(
        "--realtime",
        action=argparse.BooleanOptionalAction,
        default=vi["realtime"],
        help="Pace reads to match video FPS so wall time tracks scene time. Use --no-realtime to read as fast as possible.",
    )
    p.add_argument(
        "--loop",
        action=argparse.BooleanOptionalAction,
        default=vi["loop"],
        help="Start over when the file ends (config/video_ingest.example.json or --no-loop)",
    )
    p.add_argument(
        "--motion-scale",
        type=float,
        default=vi["motion_scale"],
        help="Only for people_source=motion: scales motion → people_count",
    )
    p.add_argument(
        "--people-source",
        choices=("yolo", "motion", "density"),
        default=vi["people_source"],
        help="yolo = YOLOv8 boxes; density = CSRNet sum(density map); motion = pixel-diff proxy",
    )
    p.add_argument("--yolo-model", default=vi["yolo_model"], help="Ultralytics model name or path (.pt)")
    p.add_argument(
        "--yolo-conf",
        type=float,
        default=vi["yolo_conf"],
        help="Final score gate after Soft-NMS / aspect filter (v3)",
    )
    p.add_argument(
        "--yolo-tile-conf",
        type=float,
        default=vi["yolo_tile_conf"],
        help="Per-tile YOLO conf (stricter; reduces junk before merge)",
    )
    p.add_argument(
        "--yolo-max-width",
        type=int,
        default=vi["yolo_max_width"],
        help="Max frame width before YOLO (faster if set, e.g. 960); 0 = full resolution",
    )
    p.add_argument(
        "--yolo-imgsz",
        type=int,
        default=vi["yolo_imgsz"],
        help="YOLO letterbox size (try 1280 for distant people; 640 is faster)",
    )
    p.add_argument(
        "--yolo-device",
        default=vi["yolo_device"],
        choices=("auto", "cpu", "mps", "cuda"),
        help="Inference device (auto picks MPS on Apple Silicon when available)",
    )
    p.add_argument(
        "--yolo-tile-grid",
        type=int,
        default=vi["yolo_tile_grid"],
        help="NxN overlapping tiles (1=off; 2=2x2, better for wide crowds; more tiles = slower)",
    )
    p.add_argument(
        "--yolo-tile-overlap",
        type=float,
        default=vi["yolo_tile_overlap"],
        help="Overlap between tiles as a fraction of each tile size (0–0.5 typical)",
    )
    p.add_argument(
        "--yolo-soft-nms-sigma",
        type=float,
        default=vi["yolo_soft_nms_sigma"],
        help="Gaussian Soft-NMS bandwidth (cross-tile dedupe)",
    )
    p.add_argument(
        "--yolo-soft-nms-score-threshold",
        type=float,
        default=vi["yolo_soft_nms_score_threshold"],
        help="Drop boxes decayed below this after Soft-NMS",
    )
    p.add_argument(
        "--yolo-ar-min",
        type=float,
        default=vi["yolo_ar_min"],
        help="Min width/height for person-shaped boxes",
    )
    p.add_argument(
        "--yolo-ar-max",
        type=float,
        default=vi["yolo_ar_max"],
        help="Max width/height for person-shaped boxes",
    )
    p.add_argument(
        "--yolo-ar-min-height-px",
        type=int,
        default=vi["yolo_ar_min_height_px"],
        help="Reject boxes shorter than this (noise)",
    )
    p.add_argument(
        "--yolo-min-tile-px",
        type=int,
        default=vi["yolo_min_tile_px"],
        help="Skip tiles smaller than this (each side); avoids tiny crops on dense grids",
    )
    p.add_argument(
        "--density-weights",
        default=vi["density_weights"],
        help="Path to CSRNet .pth (optional; if empty, downloads ShanghaiTech-A weights once)",
    )
    p.add_argument(
        "--density-max-side",
        type=int,
        default=vi["density_max_side"],
        help="Resize so max(h,w) <= this before CSRNet (lower = faster)",
    )
    p.add_argument(
        "--density-gdrive-id",
        default=vi["density_gdrive_id"],
        help="Google Drive file id for CSRNet weights (default: leeyee ShanghaiTech Part A)",
    )
    p.add_argument(
        "--density-calibration",
        type=float,
        default=vi["density_calibration"],
        help="Multiply sum(density); tune when model is low vs reality on your cameras (default 1.0)",
    )
    p.add_argument(
        "--density-multi-scale",
        action=argparse.BooleanOptionalAction,
        default=vi["density_multi_scale"],
        help="Average two CSRNet passes at different resize scales (slower, sometimes higher raw_sum)",
    )
    return p.parse_args()


def open_capture(path: Path) -> Tuple[cv2.VideoCapture, float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if fps <= 0:
        fps = 30.0
    return cap, fps


def main() -> None:
    args = parse_args()
    path_str = args.video.strip()
    path = Path(path_str).expanduser() if path_str else None
    if not path or not path.is_file():
        fallback = default_sample_video()
        if not fallback or not fallback.is_file():
            raise SystemExit(
                "No video path. Pass --video /path/to/file.mp4 or drop an .mp4 under data/samples/"
            )
        path = fallback

    sample_fps = max(0.1, float(args.sample_fps))
    cap, fps = open_capture(path)
    stride = max(1, int(round(fps / sample_fps)))

    yolo_model = None
    device = None
    density_model = None
    torch_device = None
    _density_estimate_count = None

    if args.people_source == "yolo":
        device = resolve_device(args.yolo_device)
        print(f"Loading YOLO: {args.yolo_model} (device={device}, first run may download weights)...")
        yolo_model = load_yolo(args.yolo_model)
        print(
            "Note: YOLO counts person *boxes*. Dense city-wide shots still won’t match a true headcount; "
            "tiled mode (--yolo-tile-grid 2+) helps. Try people_source=density for congested scenes."
        )
    elif args.people_source == "density":
        import torch

        from density_counter import ensure_weights, estimate_count as density_estimate_count, load_csrnet

        dev_name = resolve_device(args.yolo_device)
        torch_device = torch.device("cuda:0" if dev_name == "cuda" else dev_name)
        w_arg = (args.density_weights or "").strip()
        if w_arg:
            wp = Path(w_arg).expanduser()
            if not wp.is_file():
                raise SystemExit(f"CSRNet weights not found: {wp}")
            weights_path = wp
        else:
            gid = (args.density_gdrive_id or "").strip() or None
            weights_path = ensure_weights(gdrive_id=gid)
        print(f"Loading CSRNet density model from {weights_path} (torch device={torch_device})...")
        density_model = load_csrnet(weights_path, torch_device)
        _density_estimate_count = density_estimate_count
        print(
            "Density maps are trained on ShanghaiTech; counts on random web video are **relative**, "
            "not a ground-truth census. Use the same pipeline for trends/alerts, not legal accuracy."
        )

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    producer = build_producer(args.bootstrap_servers, args.producer_linger_ms)
    max_w = args.yolo_max_width if args.yolo_max_width > 0 else None
    yolo_dbg = ""
    if args.people_source == "yolo":
        yolo_dbg = (
            f" | yolo final={args.yolo_conf} tile_conf={args.yolo_tile_conf} imgsz={args.yolo_imgsz} "
            f"max_w={args.yolo_max_width or 'full'} tiles={args.yolo_tile_grid}x{args.yolo_tile_grid}"
        )
    elif args.people_source == "density":
        yolo_dbg = (
            f" | density max_side={args.density_max_side} cal={args.density_calibration} "
            f"multi_scale={args.density_multi_scale}"
        )
    print(
        f"Video ingest: {path.name} | topic={args.topic} | camera={args.camera_id} | "
        f"source={args.people_source} | realtime={args.realtime} | video_fps≈{fps:.2f} | "
        f"~{sample_fps} evt/s video | stride={stride} frames{yolo_dbg}"
    )

    frame_index = 0
    last_sample_gray = None
    emitted = 0
    conf_motion = 0.62

    try:
        while RUNNING:
            if args.realtime:
                t_read_start = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                if args.loop:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    last_sample_gray = None
                    frame_index = 0
                    continue
                break

            frame_index += 1

            if args.realtime:
                elapsed = time.monotonic() - t_read_start
                sleep_for = max(0.0, (1.0 / fps) - elapsed)
                if sleep_for:
                    time.sleep(sleep_for)

            if frame_index % stride != 0:
                continue

            density_raw_sum: Optional[float] = None

            if args.people_source == "yolo":
                assert yolo_model is not None and device is not None
                yolo_res = count_people(
                    yolo_model,
                    frame,
                    device=device,
                    conf=args.yolo_conf,
                    tile_conf=args.yolo_tile_conf,
                    max_width=max_w,
                    imgsz=args.yolo_imgsz,
                    tile_grid=args.yolo_tile_grid,
                    tile_overlap=args.yolo_tile_overlap,
                    soft_nms_sigma=args.yolo_soft_nms_sigma,
                    soft_nms_score_threshold=args.yolo_soft_nms_score_threshold,
                    ar_min=args.yolo_ar_min,
                    ar_max=args.yolo_ar_max,
                    ar_min_height_px=args.yolo_ar_min_height_px,
                    min_tile_px=args.yolo_min_tile_px,
                )
                people = yolo_res.count
                conf = yolo_res.mean_conf if people > 0 else 0.0
                ingest_mode = "yolo"
            elif args.people_source == "density":
                assert density_model is not None and torch_device is not None
                people, _cal_sum, density_raw_sum = _density_estimate_count(
                    density_model,
                    frame,
                    device=torch_device,
                    max_side=args.density_max_side,
                    calibration=args.density_calibration,
                    multi_scale=args.density_multi_scale,
                )
                conf = _CONF_DENSITY
                ingest_mode = "csrnet_density"
            else:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                if last_sample_gray is None:
                    last_sample_gray = gray
                    continue
                score = motion_score(last_sample_gray, gray)
                last_sample_gray = gray
                people = score_to_people_count(score, args.motion_scale, args.max_expected_occupancy)
                conf = conf_motion
                ingest_mode = "motion_proxy"

            event = make_event(
                camera_id=args.camera_id,
                zone=args.zone,
                priority=args.priority,
                max_occ=args.max_expected_occupancy,
                people_count=people,
                confidence=conf,
                ingest_mode=ingest_mode,
            )
            t_media = media_time_seconds(cap, frame_index, fps)
            event["video_time_sec"] = round(t_media, 3)
            event["video_timecode"] = format_media_timecode(t_media)
            if density_raw_sum is not None:
                event["density_raw_sum"] = round(density_raw_sum, 3)
                event["density_calibration"] = args.density_calibration
            producer.send(args.topic, key=args.camera_id, value=event)
            emitted += 1
            if emitted % 20 == 0:
                producer.flush()
                if args.people_source == "yolo":
                    extra = f"people={people}"
                elif args.people_source == "density":
                    extra = f"people≈{people} raw_sum≈{density_raw_sum:.1f} cal={args.density_calibration}"
                else:
                    extra = f"people={people} motion"
                print(f"Emitted {emitted} events ({extra}) @ video {format_media_timecode(t_media)}")

        producer.flush()
    finally:
        producer.close()
        cap.release()
        print(f"Stopped video ingest. Total events: {emitted}")


if __name__ == "__main__":
    main()
