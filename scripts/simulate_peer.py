#!/usr/bin/env python3
"""Drop fake peer messages into the federation directory.

Usage:
    python scripts/simulate_peer.py [federation_dir] [--task]

Without --task: sends a heartbeat from agent-internet-001.
With --task: sends a delegate_task asking steward to fix tests.

Watch daemon.log — steward processes these in the next DHARMA phase.
"""

import json
import os
import sys
import time

fed_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "/tmp/steward-federation"
send_task = "--task" in sys.argv
outbox = f"{fed_dir}/outbox"

messages = []

if send_task:
    # Task delegation: peer asks steward to fix something
    messages.append(
        {
            "operation": "delegate_task",
            "payload": {
                "title": "Fix failing test_api_routes in agent-internet",
                "priority": 70,
                "source_agent": "agent-internet",
                "repo": "https://github.com/user/agent-internet",
            },
            "source": "agent-internet",
            "timestamp": time.time(),
        }
    )
    label = "delegate_task"
else:
    # Heartbeat: peer announces it's alive
    messages.append(
        {
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
    )
    label = "heartbeat"

os.makedirs(outbox, exist_ok=True)
path = f"{outbox}/{time.time_ns()}.json"
with open(path, "w") as f:
    json.dump(messages, f, indent=2)

print(f"Dropped {label} → {path}")
print(f"Watch: tail -f .steward/daemon.log | grep -i 'delegate\\|heartbeat\\|federation\\|KARMA'")
