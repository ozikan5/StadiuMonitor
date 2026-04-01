"""
Fake stadium cameras: generates JSON events and pushes them to Kafka.

In production you'd get real counts from CV/ML on each camera feed. Here we just
simulate plausible numbers so you can test Kafka load and downstream consumers
without wiring up video yet.
"""

import argparse
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from faker import Faker
from kafka import KafkaProducer

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from shared.camera_registry import load_cameras as load_registry_file
from shared.kafka_config import kafka_settings

# So Ctrl+C can exit the loop cleanly instead of hanging mid-batch.
RUNNING = True
fake = Faker()


def stop_handler(signum, frame):
    del signum, frame
    global RUNNING
    RUNNING = False


def load_cameras(config_path: str, camera_count: int) -> List[Dict[str, Any]]:
    # Prefer your registry: config/cameras.json with {"cameras": [...]} (see scripts/camera.py).
    if config_path and Path(config_path).exists():
        cams = load_registry_file(Path(config_path))
        if not cams:
            raise SystemExit(
                f"No cameras in {config_path}. Add some: python scripts/camera.py add --id CAM-001 ..."
            )
        return cams

    # No file? Invent N cameras (legacy quick test only).
    print(
        f"Note: {config_path or 'config'} missing — using random synthetic cameras. "
        "Create real ones: python scripts/camera.py init && python scripts/camera.py add ...",
        file=sys.stderr,
    )
    return [
        {
            "camera_id": f"CAM-{idx:03d}",
            "zone": random.choice(["north-stand", "south-stand", "east-gate", "west-gate", "concourse"]),
            "max_expected_occupancy": random.randint(80, 260),
            "priority": random.choice(["high", "medium", "low"]),
        }
        for idx in range(1, camera_count + 1)
    ]


def generate_event(camera: Dict[str, Any]) -> Dict[str, Any]:
    # Rough bell curve around "a bit over half full" — feels more natural than flat random.
    max_occ = camera.get("max_expected_occupancy", 120)
    people_count = max(0, int(random.gauss(max_occ * 0.55, max_occ * 0.2)))
    confidence = round(random.uniform(0.78, 0.99), 3)

    return {
        "event_id": fake.uuid4(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_id": camera["camera_id"],
        "zone": camera["zone"],
        "priority": camera.get("priority", "medium"),
        "people_count": min(people_count, max_occ + random.randint(0, 15)),
        "max_expected_occupancy": max_occ,
        "estimated_queue_length": max(0, people_count - int(max_occ * 0.8)),
        "detection_confidence": confidence,
    }


def build_producer(bootstrap_servers: str, linger_ms: int) -> KafkaProducer:
    # bootstrap_servers is where Kafka listens (your docker-compose maps 9092 on localhost).
    # Key = camera_id so related events can land in the same partition if you scale later.
    return KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        linger_ms=linger_ms,
    )


def parse_args() -> argparse.Namespace:
    ks = kafka_settings()
    parser = argparse.ArgumentParser(description="Stadium camera data simulator")
    parser.add_argument("--bootstrap-servers", default=ks["bootstrap_servers"])
    parser.add_argument("--topic", default=ks["topic"])
    parser.add_argument(
        "--producer-linger-ms",
        type=int,
        default=ks["producer_linger_ms"],
        help="Kafka producer batching delay (see shared/kafka_config.py)",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("CAMERA_CONFIG", "config/cameras.json"),
        help="Camera registry JSON (default: config/cameras.json from scripts/camera.py)",
    )
    parser.add_argument("--camera-count", type=int, default=int(os.getenv("CAMERA_COUNT", "50")))
    parser.add_argument("--events-per-second", type=float, default=float(os.getenv("EVENTS_PER_SECOND", "20")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # Spread events evenly across the second (20 eps → sleep ~0.05s between sends).
    interval = 1.0 / max(args.events_per_second, 0.1)
    cameras = load_cameras(args.config, args.camera_count)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    producer = build_producer(args.bootstrap_servers, args.producer_linger_ms)
    print(
        f"Producing events to topic='{args.topic}' on {args.bootstrap_servers} "
        f"from {len(cameras)} cameras at ~{args.events_per_second} eps"
    )

    produced = 0
    try:
        while RUNNING:
            # Pick a random camera each tick — mimics many feeds reporting at different times.
            camera = random.choice(cameras)
            event = generate_event(camera)
            producer.send(args.topic, key=event["camera_id"], value=event)
            produced += 1

            # Flush occasionally so you don't buffer forever if the process dies.
            if produced % 200 == 0:
                producer.flush()
                print(f"Produced {produced} events...")

            time.sleep(interval)
    finally:
        producer.flush()
        producer.close()
        print(f"Stopped producer. Total events produced: {produced}")


if __name__ == "__main__":
    main()
