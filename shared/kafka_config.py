"""
Load Kafka connection defaults from config files, with env vars on top.

Precedence: environment variables win, then config file, then built-in defaults.

Files (first match wins):
  config/kafka.json       — local overrides (gitignored)
  config/kafka.example.json — committed template
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_kafka_config() -> Dict[str, Any]:
    root = repo_root()
    for name in ("kafka.json", "kafka.example.json"):
        path = root / "config" / name
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def kafka_settings() -> Dict[str, Any]:
    cfg = load_kafka_config()
    prod = cfg.get("producer") or {}
    linger = prod.get("linger_ms", 20)
    if os.getenv("KAFKA_PRODUCER_LINGER_MS"):
        linger = int(os.environ["KAFKA_PRODUCER_LINGER_MS"])

    return {
        "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS") or cfg.get("bootstrap_servers", "localhost:9092"),
        "topic": os.getenv("KAFKA_TOPIC") or cfg.get("topic", "stadium.camera.events"),
        "consumer_group": os.getenv("KAFKA_CONSUMER_GROUP") or cfg.get("consumer_group", "stadium-ops-monitor"),
        "producer_linger_ms": linger,
    }
