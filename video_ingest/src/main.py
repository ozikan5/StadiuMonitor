"""
Play a video file like one camera feed: sample frames, derive a rough activity
signal, publish the same JSON shape as simulator/src/camera_simulator.py.

This is a stepping stone before a real person detector (YOLO etc.): motion
across sampled frames is not "people count," but it tracks activity changes
and exercises the Kafka path with real pixels.
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

RUNNING = True


def stop_handler(signum, frame):
    del signum, frame
    global RUNNING
    RUNNING = False


def project_root() -> Path:
    # video_ingest/src/main.py -> repo root is two levels up from src
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
        help="Higher => larger people_count from the same motion (tune per clip)",
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

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    producer = build_producer(args.bootstrap_servers, args.producer_linger_ms)
    print(
        f"Video ingest: {path.name} | topic={args.topic} | camera={args.camera_id} | "
        f"realtime={args.realtime} | video_fps≈{fps:.2f} | ~{sample_fps} evt/s video | stride={stride} frames"
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

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if frame_index % stride != 0:
                continue

            if last_sample_gray is None:
                last_sample_gray = gray
                continue

            score = motion_score(last_sample_gray, gray)
            last_sample_gray = gray
            people = score_to_people_count(score, args.motion_scale, args.max_expected_occupancy)

            event = make_event(
                camera_id=args.camera_id,
                zone=args.zone,
                priority=args.priority,
                max_occ=args.max_expected_occupancy,
                people_count=people,
                confidence=conf_motion,
                ingest_mode="motion_proxy",
            )
            producer.send(args.topic, key=args.camera_id, value=event)
            emitted += 1
            if emitted % 50 == 0:
                producer.flush()
                print(f"Emitted {emitted} events (last people_count={people}, motion_mean={score:.2f})")

        producer.flush()
    finally:
        producer.close()
        cap.release()
        print(f"Stopped video ingest. Total events: {emitted}")


if __name__ == "__main__":
    main()
