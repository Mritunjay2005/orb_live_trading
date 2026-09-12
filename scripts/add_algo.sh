#!/usr/bin/env bash
# Usage: ./scripts/add_algo.sh 5 strategies.my_new_strategy "NSE_EQ:TCS"
# Adds a 5th (or Nth) algo pod to docker-compose.yml.
set -euo pipefail
N=$1
STRATEGY_MODULE=$2
INSTRUMENTS=$3

cat >> ../docker-compose.yml << YAML

  algo-pod-${N}:
    build: ./algo-pod
    restart: unless-stopped
    env_file: .env
    environment:
      - POD_ID=algo-pod-${N}
      - STRATEGY_MODULE=${STRATEGY_MODULE}
      - INSTRUMENTS=${INSTRUMENTS}
      - EXECUTION_GATE_URL=http://execution-gate:8000
      - QUEUE_SERVICE_URL=http://queue-service:8000
    volumes:
      - ./algo-pod/strategies:/app/strategies:ro
    networks: [trading-net]
    depends_on: [execution-gate, queue-service]
YAML

echo "Added algo-pod-${N}. Now run: docker compose up -d --build algo-pod-${N}"
