# StadiuMonitor (Phase 1 Scaffold)

Starter framework for simulating stadium camera telemetry with Apache Kafka.

This first phase focuses on **synthetic data generation** so you can model many camera feeds and validate ingestion + basic operational logic before integrating real CV pipelines.

## Project Structure

```text
.
├── consumer/
│   ├── requirements.txt
│   └── src/main.py
├── data/
│   └── samples/          # drop local MP4s here (gitignored)
├── config/
│   ├── kafka.example.json        # broker / topic / consumer group
│   └── video_ingest.example.json # zone, max occupancy, motion tuning (video path)
├── docs/
│   └── architecture.md
├── infra/
│   └── kafka/
├── shared/
│   └── kafka_config.py      # loads Kafka defaults (file + env)
├── simulator/
│   ├── config/cameras.example.json
│   ├── requirements.txt
│   └── src/
│       ├── camera_simulator.py
│       └── main.py
├── video_ingest/
│   ├── requirements.txt
│   └── src/main.py       # optional: MP4 → Kafka (motion proxy until real CV)
├── scripts/
│   └── bootstrap.sh
├── docker-compose.yml
└── README.md
```

## What This Gives You

- Local Kafka + Zookeeper via Docker Compose
- A Python camera simulator that publishes fake events to Kafka
- Optional **video ingest**: read an MP4 from `data/samples/`, pace like live video, publish the same event shape (motion-based proxy counts until you add a detector)
- A basic consumer that reads events and raises occupancy alerts
- A starter event contract and architecture doc for future phases

## Prerequisites

- Docker + Docker Compose
- Python 3.10+

## Quick Start

1. Bootstrap Python environment and dependencies:

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

2. Start Kafka infrastructure:

```bash
docker compose up -d
```

3. Run the simulator (example: 200 cameras at 50 events/sec):

```bash
python simulator/src/main.py --camera-count 200 --events-per-second 50
```

4. In another terminal, run the consumer:

```bash
python consumer/src/main.py
```

### Optional: use your MP4 instead of the random simulator

1. Put a file under `data/samples/` (e.g. your 720p clip). Large files stay **local**; `*.mp4` there is gitignored by default.
2. With Kafka still up and venv active:

```bash
python video_ingest/src/main.py --video "data/samples/YOUR_FILE.mp4" --camera-id CAM-TIMESQ-001 --zone street-demo
```

Omit `--video` to pick the **first** `data/samples/*.mp4` alphabetically.  
`--no-realtime` reads the file as fast as possible (good for soaking tests).  
Tune `--motion-scale` if counts look flat or too wild.

## Kafka configuration (optional)

Defaults live in `config/kafka.example.json`: **how to reach Kafka** (broker, topic, consumer group, producer `linger_ms`). It does **not** hold per-camera business fields like `max_expected_occupancy`—those belong elsewhere (see below).

- Copy to `config/kafka.json` if you want local overrides without editing the example file (`kafka.json` is gitignored).
- **Environment variables still override** the file: `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC`, `KAFKA_CONSUMER_GROUP`, `KAFKA_PRODUCER_LINGER_MS`.

Used by the simulator, video ingest, and consumer via `shared/kafka_config.py`.

### Video ingest defaults (zone, max occupancy, etc.)

For the **single-feed** video path, stadium-like fields live in `config/video_ingest.example.json`: `camera_id`, `zone`, `priority`, `max_expected_occupancy`, `sample_fps`, `motion_scale`, `realtime`, `loop`.

- Copy to `config/video_ingest.json` for local tweaks (gitignored).
- Env overrides: `VIDEO_CAMERA_ID`, `VIDEO_ZONE`, `VIDEO_PRIORITY`, `VIDEO_MAX_OCCUPANCY`, `VIDEO_SAMPLE_FPS`, `VIDEO_MOTION_SCALE`, `VIDEO_REALTIME`, `VIDEO_LOOP`.

The **multi-camera simulator** still uses `simulator/config/cameras.example.json` (a list of cameras).

## Simulator Configuration

The simulator can load camera metadata from `simulator/config/cameras.example.json`.

CLI options:

- `--bootstrap-servers` (default: `localhost:9092`)
- `--topic` (default: `stadium.camera.events`)
- `--config` (default: `simulator/config/cameras.example.json`)
- `--camera-count` (used when no config file exists; default: `50`)
- `--events-per-second` (default: `20`)

## Event Example

```json
{
  "event_id": "9688b2bb-2009-4aa4-88ee-f6d9ee2c5520",
  "timestamp": "2026-03-30T17:00:00.123456+00:00",
  "camera_id": "CAM-NORTH-001",
  "zone": "north-stand",
  "priority": "high",
  "people_count": 137,
  "max_expected_occupancy": 220,
  "estimated_queue_length": 0,
  "detection_confidence": 0.941
}
```

## Suggested Next Steps (Phase 2+)

- Add schema validation (Avro/Protobuf + Schema Registry)
- Add stream processor for per-zone rolling occupancy
- Save aggregates to a timeseries or OLAP store
- Build a staffing recommendation module (rules + ML)
- Add dashboard + alert integration (Slack/PagerDuty/etc.)

## Notes

- This is intentionally lightweight and simulation-first.
- `infra/kafka/` is reserved for future broker config and topic bootstrap scripts.
