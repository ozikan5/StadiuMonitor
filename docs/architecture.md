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

## Crowd counts (video ingest)
CSRNet was trained on **ShanghaiTech Part A**. On **other** footage (e.g. downloaded city cams), raw `sum(density)` is often **far below** eyeball or venue counts (2–4× is common). That is mostly **domain gap**, not a Kafka bug.

**Practical tuning (in order):**
1. Raise `density_max_side` (e.g. 1280–1536) if CPU/MPS can handle it; try `--density-multi-scale`.
2. Set **`density_calibration ≈ (your trusted count) / density_raw_sum`** from one representative frame or clip (e.g. 250 ÷ 70 ≈ 3.6). Use the same factor for operational **trends** until you can fine-tune on your venue.
3. For production accuracy: **ROI crop** (stands only), **fixed camera geometry**, and/or **fine-tuned** density or detector on labeled stadium frames.

## Next Iterations
- Add schema registry / versioned schemas (Avro/Protobuf)
- Add stream processing for zone-level aggregates
- Persist to OLAP/warehouse for dashboards
- Add staffing recommendation engine and alert routing
