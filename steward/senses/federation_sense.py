"""
FederationSense — Cross-repo awareness for the federation.

A Jnanendriya (knowledge sense) that reads the state of ALL
federation repos, not just steward's own. Pulls nadi outboxes,
CI status, health reports from every peer.

Without this, steward is blind beyond its own repo. With it,
steward perceives the entire federation as ONE organism.

The senses are limited (like material senses). Every new metric
we collect expands the system's consciousness.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.SENSE.FEDERATION")


def scan_federation_state() -> dict:
    """Scan all federation peers and return aggregate state.

    Reads from GitHub API — each repo's:
    - Latest CI status
    - Nadi outbox (if exists)
    - Federation descriptor status
    - Last commit age

    Returns a dict that represents the federation's ACTUAL state,
    not what steward THINKS the state is.
    """
    from steward.hooks.genesis import _get_federation_owner, _gh

    owner = _get_federation_owner()
    if not owner:
        return {"error": "no federation owner", "peers": {}}

    # Get all repos
    raw = _gh(["repo", "list", owner, "--json", "name,pushedAt", "--limit", "100"])
    if not raw:
        return {"error": "cannot list repos", "peers": {}}

    try:
        repos = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"error": "cannot parse repo list", "peers": {}}

    peers: dict[str, dict] = {}

    for repo in repos:
        name = repo.get("name", "")
        if not name:
            continue

        peer_state: dict = {
            "name": name,
            "last_push": repo.get("pushedAt", ""),
        }

        # CI status (latest run)
        ci_raw = _gh(["run", "list", "--repo", f"{owner}/{name}",
                       "--limit", "1", "--json", "conclusion,workflowName"])
        if ci_raw:
            try:
                runs = json.loads(ci_raw)
                if runs:
                    peer_state["ci_conclusion"] = runs[0].get("conclusion", "unknown")
                    peer_state["ci_workflow"] = runs[0].get("workflowName", "")
            except (json.JSONDecodeError, TypeError):
                pass

        # Federation descriptor
        desc_raw = _gh(["api", f"repos/{owner}/{name}/contents/.well-known/agent-federation.json",
                         "--jq", ".content"])
        peer_state["has_descriptor"] = bool(desc_raw and desc_raw.strip())

        # Nadi outbox
        outbox_raw = _gh(["api", f"repos/{owner}/{name}/contents/data/federation/nadi_outbox.json",
                           "--jq", ".size"])
        if outbox_raw and outbox_raw.strip().isdigit():
            peer_state["outbox_size"] = int(outbox_raw.strip())
        else:
            peer_state["outbox_size"] = 0

        peers[name] = peer_state

    # Aggregate
    total = len(peers)
    with_descriptor = sum(1 for p in peers.values() if p.get("has_descriptor"))
    ci_green = sum(1 for p in peers.values() if p.get("ci_conclusion") == "success")
    ci_red = sum(1 for p in peers.values() if p.get("ci_conclusion") == "failure")
    sending = sum(1 for p in peers.values() if p.get("outbox_size", 0) > 10)

    return {
        "timestamp": time.time(),
        "owner": owner,
        "summary": {
            "total_repos": total,
            "with_descriptor": with_descriptor,
            "without_descriptor": total - with_descriptor,
            "ci_green": ci_green,
            "ci_red": ci_red,
            "actively_sending": sending,
        },
        "peers": peers,
    }
