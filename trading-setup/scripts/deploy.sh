#!/usr/bin/env bash
# Run this ON the Oracle Cloud instance (after terraform apply + SSH in).
set -euo pipefail
cd /opt/trading

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill in your keys first."
  exit 1
fi

docker compose pull || true
docker compose up -d --build
docker compose ps
