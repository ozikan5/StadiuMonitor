# Architecture (Phase 1)

## What we’re building

A small **streaming spine**: camera-style occupancy events land on Kafka so we can exercise consumers, alerts, and later real analytics—without pretending the first cut is production-grade CV.

## What’s in the loop today

- **Kafka** — single topic for camera-shaped JSON events.
- **Simulator** — fake counts + metadata when we just need load or plumbing tests.
- **Video ingest** — optional path from local MP4s into the **same** event shape (motion, YOLO, or density—depending what we care about that day).
- **Consumer** — reads the topic and does a simple threshold sanity check; the interesting stuff will sit downstream later.

So we’re not locked into “random numbers only” anymore: one repo can behave like **many feeds** or **one file**, but the **contract** stays the same.

## Owning cameras (registry)

We moved away from living out of checked-in examples. There’s a **local registry** (not committed) where we define cameras—zones, caps, priorities, and optionally a file to drive video ingest. The simulator and the multi-feed runner both **prefer that list** when it exists, so we’re not copy-pasting JSON or rediscovering flags every time.

That’s the main “we actually use this day to day” change from the original scaffold.

## Data contract (v0)

Each event roughly has:

- `event_id`, `timestamp` (UTC)
- `camera_id`, `zone`, `priority`
- `people_count`, `max_expected_occupancy`, `estimated_queue_length`
- `detection_confidence`

Video ingest may add small extras (e.g. how it was produced); the core fields stay stable for the consumer.

## Crowd counts — expectations

Dense scenes break naive **box counts**; density models help but they’re **trained on specific data**, so random street footage won’t match “true” headcount. That’s normal—it’s a **sense of load**, not a census—until we calibrate on **our** venue and cameras.

**Real-world check:** On a very busy Times Square–style clip (roughly a few hundred people in frame), everything we tried still sat much lower (on the order of tens to low hundreds). For experiments I nudged CSRNet output with a rough global scale so numbers sat in a believable range; that’s a **hack for demos**, not something to trust across new angles or venues. Longer term it’s ROI, geometry, and/or models tuned on our own frames—not one magic multiplier.

## Where this probably goes next

- Stronger **schemas** and versioning once more than one service cares about the payload.
- **Zone-level** rollups and a place to **store** them so we’re not inferring ops state from a log tail.
- Staffing / routing hints on top of that.

---

*Phase 1 is deliberately boring on purpose: Kafka + one shape + a few ways to populate it. Everything interesting hangs off that spine.*
