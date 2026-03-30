"""
Reads camera events from Kafka — the "downstream" side of the pipeline.

The simulator writes JSON to a topic; this script subscribes and reacts (here:
just print + a simple over-capacity alert). Later you can swap this for
aggregations, dashboards, or staffing rules.
"""

import json
import os
from collections import defaultdict

from kafka import KafkaConsumer


def main() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", "stadium.camera.events")
    # Consumer group: Kafka remembers how far this group has read. Handy if you run
    # multiple instances later — they share the load without duplicating every message.
    group = os.getenv("KAFKA_CONSUMER_GROUP", "stadium-ops-monitor")

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=group,
        # If this is a brand-new group, start from the oldest message so you don't miss the sim.
        auto_offset_reset="earliest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )

    # Placeholder for "last seen count per zone" — you might sum cameras per zone later.
    zone_counts = defaultdict(int)
    print(f"Listening on topic='{topic}' via {bootstrap} as group='{group}'")

    for msg in consumer:
        payload = msg.value
        zone = payload.get("zone", "unknown")
        people = int(payload.get("people_count", 0))
        zone_counts[zone] = people

        # Crude threshold: more people than this camera's configured cap.
        if people > payload.get("max_expected_occupancy", 0):
            print(
                "[ALERT] Occupancy threshold exceeded "
                f"camera={payload.get('camera_id')} zone={zone} people={people}"
            )
        else:
            print(f"[EVENT] camera={payload.get('camera_id')} zone={zone} people={people}")


if __name__ == "__main__":
    main()
