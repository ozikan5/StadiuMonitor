# StadiuMonitor (Phase 1 Scaffold)

Kafka-backed telemetry for stadium-style camera events: **synthetic simulation**, **optional MP4 ingest** (YOLO / CSRNet density / motion), and a small consumer for alerts.

---

## Modes at a glance

| Mode | Command | When to use |
| --- | --- | --- |
| **Synthetic simulation** | `python simulator/src/main.py …` | Fake `people_count` to load-test Kafka and consumers. Reads `config/cameras.json` if present; otherwise invents cameras. |
| **Video → Kafka (one file)** | `python video_ingest/src/main.py …` | One MP4, one `camera_id` / zone; same event JSON as the simulator. |
| **Video → Kafka (registry)** | `python scripts/run_video_feeds.py …` | One `video_ingest` process per camera in `config/cameras.json` that has `feed.type: file`. |
| **Downstream** | `python consumer/src/main.py` | Subscribe to the topic; prints events and simple over-capacity alerts. |
| **Camera list** | `python scripts/camera.py …` | Create/edit the registry file (`init`, `add`, `list`, `remove`) — not a Kafka producer. |

Simulation and video ingest **both publish** to the same topic shape; they are **alternatives** for producing events (do not need to run both at once unless you want mixed load).

---

## Project structure

```text
.
├── consumer/src/main.py
├── config/                    # kafka.example.json, video_ingest.example.json; local overrides gitignored
├── data/samples/              # local MP4s (gitignored patterns)
├── shared/                    # kafka_config, video_ingest_config, camera_registry
├── simulator/src/             # camera_simulator.py (+ main.py wrapper)
├── video_ingest/src/main.py
├── scripts/bootstrap.sh, camera.py, run_video_feeds.py
└── docker-compose.yml
```

---

## Quick start

```bash
./scripts/bootstrap.sh && source .venv/bin/activate
docker compose up -d
```

**Simulated cameras** (registry optional):

```bash
python simulator/src/main.py --events-per-second 50
# If config/cameras.json is missing: adds random cameras; use --camera-count N
```

**Consumer** (another terminal):

```bash
python consumer/src/main.py
```

**One video file**:

```bash
python video_ingest/src/main.py --video "data/samples/your.mp4" --camera-id CAM-001 --zone demo
```

**Registry-backed video** (after `camera.py add … --video …`):

```bash
python scripts/run_video_feeds.py
```

---

## Configuration files

| File | Role |
| --- | --- |
| `config/kafka.example.json` | Bootstrap servers, topic, consumer group, producer `linger_ms`. Copy to `config/kafka.json` for local overrides (gitignored). |
| `config/video_ingest.example.json` | Defaults for **single-file** video ingest: ids, fps, YOLO/density, realtime/loop. Copy to `config/video_ingest.json` (gitignored). |
| `config/cameras.json` | Your cameras: `camera_id`, zone, caps, optional `feed` + `ingest`. Managed with `scripts/camera.py` or by hand (gitignored). |

**Kafka env overrides** (used by simulator, video ingest, consumer): `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC`, `KAFKA_CONSUMER_GROUP`, `KAFKA_PRODUCER_LINGER_MS`.

**Video ingest env** (see `shared/video_ingest_config.py` for full list): e.g. `VIDEO_CAMERA_ID`, `VIDEO_ZONE`, `VIDEO_PEOPLE_SOURCE`, `VIDEO_YOLO_*`, `VIDEO_DENSITY_*`, `CSRNET_GDRIVE_ID`.

---

## Camera registry

```bash
python scripts/camera.py init
python scripts/camera.py add --id CAM-NORTH-001 --zone north-stand --max-occ 220 --priority high
python scripts/camera.py add --id CAM-PLAZA-001 --zone plaza --max-occ 300 --video data/samples/clip.mp4
python scripts/camera.py list
python scripts/camera.py remove --id CAM-PLAZA-001
```

- Simulator: `--config` defaults to `config/cameras.json` (env: `CAMERA_CONFIG`). If the file is **missing**, synthetic cameras are used (`CAMERA_COUNT` / `--camera-count`). If the file **exists** but has **no cameras**, the simulator exits.
- `run_video_feeds.py` only spawns processes for cameras with `feed: { "type": "file", "path": "..." }`.
- Optional per-camera **`ingest`** JSON keys (passed through to `video_ingest` CLI): `people_source`, `density_*`, `sample_fps`, `motion_scale`, `max_expected_occupancy`, `priority`, `realtime`, `loop`, and YOLO v3 fields such as `yolo_conf`, `yolo_tile_conf`, `yolo_soft_nms_sigma`, `yolo_ar_min`, `yolo_min_tile_px`, etc.

`simulator/config/cameras.example.json` is a **schema example**, not the runtime default path.

---

## CLI reference

### Synthetic simulator — `python simulator/src/main.py`

| Argument | Default | Notes |
| --- | --- | --- |
| `--bootstrap-servers` | from `kafka_settings()` | |
| `--topic` | from kafka config | |
| `--producer-linger-ms` | from kafka config | Producer batching delay |
| `--config` | `config/cameras.json` | Env: `CAMERA_CONFIG` |
| `--camera-count` | `50` | Env: `CAMERA_COUNT`. **Only used if `--config` file is missing.** |
| `--events-per-second` | `20` | Env: `EVENTS_PER_SECOND` |

---

### Video ingest — `python video_ingest/src/main.py`

Defaults come from `config/video_ingest*.json` and env unless overridden on the CLI.

#### Connection & I/O

| Argument | Default | Notes |
| --- | --- | --- |
| `--video` | `""` → first `data/samples/*.mp4` | Env: `VIDEO_PATH` |
| `--bootstrap-servers`, `--topic`, `--producer-linger-ms` | kafka config | Same idea as simulator |

#### Stadium metadata (single-feed)

| Argument | Default | Notes |
| --- | --- | --- |
| `--camera-id` | video_ingest config | |
| `--zone` | video_ingest config | |
| `--priority` | video_ingest config | |
| `--max-expected-occupancy` | video_ingest config | Used for scaling caps / alerts |

#### Playback

| Argument | Default | Notes |
| --- | --- | --- |
| `--sample-fps` | from config | Target events per second of **video timeline** |
| `--realtime` / `--no-realtime` | from config | Wall clock vs read-as-fast-as-possible |
| `--loop` / `--no-loop` | from config | Rewind when file ends |

#### Detector: `--people-source`

| Value | Meaning |
| --- | --- |
| `yolo` | YOLOv8 person boxes (default). |
| `density` | CSRNet density map; `sum` scaled by calibration — strong for **dense** crowds, **weak OOD** on random footage. |
| `motion` | Fast pixel-diff proxy; use `--motion-scale`. |

#### When `people_source=motion`

| Argument | Default | Notes |
| --- | --- | --- |
| `--motion-scale` | from config | Maps motion score → `people_count` |

#### When `people_source=yolo`

| Argument | Default | Notes |
| --- | --- | --- |
| `--yolo-model` | from config | e.g. `yolov8n.pt` |
| `--yolo-conf` | from config | Final score gate after Soft-NMS + aspect filter |
| `--yolo-tile-conf` | from config | Stricter conf on each tile/crop before merge |
| `--yolo-max-width` | from config | `0` = full frame width |
| `--yolo-imgsz` | from config | Letterbox size (e.g. 1280 for small figures) |
| `--yolo-device` | `auto` | `auto`, `cpu`, `mps`, `cuda` |
| `--yolo-tile-grid` | from config | `1` = off; `2` = 2×2 tiles |
| `--yolo-tile-overlap` | from config | Fraction of tile size |
| `--yolo-soft-nms-sigma` | from config | Gaussian Soft-NMS across merged tiles |
| `--yolo-soft-nms-score-threshold` | from config | Drop boxes decayed below this |
| `--yolo-ar-min` / `--yolo-ar-max` | from config | Allowed width/height ratio band |
| `--yolo-ar-min-height-px` | from config | Min box height (px) |
| `--yolo-min-tile-px` | from config | Skip tiny tiles |

#### When `people_source=density`

| Argument | Default | Notes |
| --- | --- | --- |
| `--density-weights` | from config | Local `.pth`; empty → download via `gdown` |
| `--density-max-side` | from config | Resize max(h,w) before CSRNet |
| `--density-gdrive-id` | from config | Weights file id if downloading |
| `--density-calibration` | from config | Multiply raw density sum (tune OOD vs your venue) |
| `--density-multi-scale` / `--no-density-multi-scale` | from config | Two-scale average (slower) |

**Practical note:** YOLO counts **boxes**, not a census; wide or dense shots often read low. Tiling helps; v3 uses **Soft-NMS**, **aspect-ratio** filtering, and **two-stage** conf (`tile_conf` vs final `yolo_conf`). Density counts are **relative** off-domain; use `density_calibration` and larger `density_max_side` for a better match, not legal ground truth.

---

### Multi-feed launcher — `python scripts/run_video_feeds.py`

| Argument | Default | Notes |
| --- | --- | --- |
| `--registry` | `config/cameras.json` | Override registry path |
| `--dry-run` | off | Print commands only |

---

### Registry tool — `python scripts/camera.py`

| Subcommand | Arguments | Action |
| --- | --- | --- |
| `init` | `--force` | Create empty `config/cameras.json`; overwrite if `--force`. |
| `add` | `--id`, `--zone`, `--max-occ`, `--priority`, `--video` (optional) | Append one camera |
| `list` | — | Print cameras |
| `remove` | `--id` | Drop by `camera_id` |
| `path` | — | Print registry file path |

---

## Event shape (Kafka value)

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

Video ingest may also set `ingest_mode`. See `docs/architecture.md` for pipeline notes.

---

## Suggested next steps (Phase 2+)

- Schema validation (Avro/Protobuf + Schema Registry)
- Stream processing / per-zone aggregates
- Timeseries or OLAP storage, dashboards, alerting (Slack/PagerDuty, etc.)

---

## Notes

- `infra/kafka/` is reserved for future broker/topic automation.
- Consumer has **no CLI flags**; it uses `shared/kafka_config` like the producers.
