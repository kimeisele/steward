#!/usr/bin/env python3
"""Drop fake peer messages into the federation directory.

Usage:
    python scripts/simulate_peer.py [federation_dir] [--task] [--check-callbacks]

Without flags: sends a heartbeat from agent-internet-001.
With --task: sends a delegate_task asking steward to fix tests.
With --check-callbacks: reads steward's inbox for task_completed/task_failed.

Watch daemon.log — steward processes these in the next DHARMA phase.
"""

import json
import os
import sys
import time
from pathlib import Path

fed_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "/tmp/steward-federation"
send_task = "--task" in sys.argv
check_callbacks = "--check-callbacks" in sys.argv
outbox = f"{fed_dir}/outbox"
inbox = f"{fed_dir}/inbox"

if check_callbacks:
    # Read steward's inbox for callback events
    inbox_path = Path(inbox)
    if not inbox_path.exists():
        print(f"No inbox at {inbox}")
        sys.exit(0)

    for f in sorted(inbox_path.glob("*.json")):
        data = json.loads(f.read_text())
        msgs = data if isinstance(data, list) else [data]
        for msg in msgs:
            op = msg.get("operation", "?")
            if op in ("task_completed", "task_failed"):
                payload = msg.get("payload", {})
                print(
                    f"  {op}: task='{payload.get('task_title', '?')}' "
                    f"from={payload.get('source_agent', '?')} "
                    f"pr={payload.get('pr_url', 'N/A')} "
                    f"error={payload.get('error', 'N/A')}"
                )
    sys.exit(0)

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
print("Watch: tail -f .steward/daemon.log | grep -i 'delegate\\|heartbeat\\|federation\\|KARMA\\|workspace'")
print(f"Check callbacks: python scripts/simulate_peer.py {fed_dir} --check-callbacks")
