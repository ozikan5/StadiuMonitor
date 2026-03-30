#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is not installed or not available on PATH."
  echo "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Error: Docker daemon is not running."
  echo "Start Docker Desktop, wait until it is ready, then run this script again."
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r simulator/requirements.txt
pip install -r consumer/requirements.txt

echo "Bootstrap complete."
echo "Start Kafka:    docker compose up -d"
echo "Run simulator:  python simulator/src/main.py --events-per-second 50 --camera-count 200"
echo "Run consumer:   python consumer/src/main.py"
