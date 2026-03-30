# Architecture (Phase 1)

## Goal
Create a streaming backbone that ingests synthetic camera occupancy events at scale.

## Components
- **Kafka**: Event bus for camera telemetry.
- **Simulator Service**: Produces fake camera events (`stadium.camera.events`).
- **Consumer Service**: Reads events and performs basic threshold checks.

## Data Contract (v0)
Each event currently includes:
- `event_id`
- `timestamp` (UTC ISO-8601)
- `camera_id`
- `zone`
- `priority`
- `people_count`
- `max_expected_occupancy`
- `estimated_queue_length`
- `detection_confidence`

## Next Iterations
- Add schema registry / versioned schemas (Avro/Protobuf)
- Add stream processing for zone-level aggregates
- Persist to OLAP/warehouse for dashboards
- Add staffing recommendation engine and alert routing
