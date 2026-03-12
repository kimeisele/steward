#!/usr/bin/env bash
# Run steward as a persistent daemon.
# Boots once, stays alive — Cetana heartbeat drives autonomous work.
# Kill with: kill $(cat .steward/daemon.pid)
STEWARD_DIR="${1:-$(pwd)}"
cd "$STEWARD_DIR"
mkdir -p .steward
echo $$ > .steward/daemon.pid
exec python -m steward --autonomous >> .steward/daemon.log 2>&1
