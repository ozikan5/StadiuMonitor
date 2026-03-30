# StadiuMonitor (Phase 1 Scaffold)

Starter framework for simulating stadium camera telemetry with Apache Kafka.

This first phase focuses on **synthetic data generation** so you can model many camera feeds and validate ingestion + basic operational logic before integrating real CV pipelines.

## Project Structure

```text
.
├── consumer/
│   ├── requirements.txt
│   └── src/main.py
├── docs/
│   └── architecture.md
├── infra/
│   └── kafka/
├── simulator/
│   ├── config/cameras.example.json
│   ├── requirements.txt
│   └── src/
│       ├── camera_simulator.py
│       └── main.py
├── scripts/
│   └── bootstrap.sh
├── docker-compose.yml
└── README.md
```

## What This Gives You

- Local Kafka + Zookeeper via Docker Compose
- A Python camera simulator that publishes fake events to Kafka
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
