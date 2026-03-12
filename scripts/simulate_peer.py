#!/usr/bin/env python3
"""Drop a fake peer heartbeat into the federation directory.

Usage:
    python scripts/simulate_peer.py [federation_dir]

Simulates agent-internet sending a heartbeat to steward.
Watch daemon.log — steward should process it in the next DHARMA phase.
"""
import json
import sys
import time

fed_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/steward-federation"
outbox = f"{fed_dir}/outbox"

# This goes into steward's OUTBOX (= messages FROM other agents TO steward)
heartbeat = {
    "operation": "heartbeat",
    "payload": {
        "agent_id": "agent-internet-001",
        "health": 0.85,
        "timestamp": time.time(),
        "capabilities": ["web_search", "http_fetch", "wiki_sync"],
    },
    "source": "agent-internet",
    "timestamp": time.time(),
}

import os
os.makedirs(outbox, exist_ok=True)
path = f"{outbox}/{time.time_ns()}.json"
with open(path, "w") as f:
    json.dump([heartbeat], f, indent=2)

print(f"Dropped heartbeat from agent-internet-001 → {path}")
print(f"Watch: tail -f .steward/daemon.log | grep -i 'heartbeat\\|federation\\|reaper\\|DHARMA'")
