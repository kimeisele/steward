# Federation Deployment Guide

Boot a Steward federation node in 3 steps.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Steward Daemon (systemd)                           │
│                                                     │
│  Cetana Heartbeat (0.1-0.5 Hz)                      │
│  ┌─────────┐  ┌─────────┐  ┌───────┐  ┌─────────┐ │
│  │ GENESIS  │→ │ DHARMA  │→ │ KARMA │→ │ MOKSHA  │ │
│  │ discover │  │ pull    │  │ work  │  │ push    │ │
│  │ tasks    │  │ + route │  │ tasks │  │ + save  │ │
│  └─────────┘  └────┬────┘  └───────┘  └────┬────┘ │
│                     │                        │      │
│            ┌────────▼────────┐      ┌────────▼────┐ │
│            │ NadiFedTransport│      │ GitNadiSync │ │
│            │ (file I/O)     │      │ (git push)  │ │
│            └────────┬────────┘      └────────┬────┘ │
│                     │                        │      │
│            ┌────────▼────────────────────────▼────┐ │
│            │  /opt/steward/federation/            │ │
│            │  ├── nadi_inbox.json  (outbound)     │ │
│            │  └── nadi_outbox.json (inbound)      │ │
│            └────────┬────────────────────────┬────┘ │
└─────────────────────┼────────────────────────┼──────┘
                      │ git push               │ git pull
                      ▼                        ▼
              ┌───────────────────────────────────┐
              │  GitHub Wiki Repo (shared remote) │
              │  github.com/org/repo.wiki.git     │
              └───────────────────────────────────┘
                      ▲                        ▲
                      │ git push               │ git pull
              ┌───────┴────────┐      ┌────────┴──────┐
              │ agent-city     │      │ agent-internet │
              │ (FederationNadi│      │ (WikiSync)     │
              └────────────────┘      └────────────────┘
```

## Step 1: Setup the Node

```bash
# On a fresh Linux server (Ubuntu 22.04+ / Debian 12+):
sudo bash deploy/setup-node.sh git@github.com:kimeisele/steward.wiki.git
```

This creates:
- `/opt/steward/workspace/` — steward codebase
- `/opt/steward/federation/` — git clone of wiki repo (nadi files)
- `/opt/steward/venv/` — Python virtualenv
- `/opt/steward/.env` — environment config (API keys)

## Step 2: Configure API Keys

```bash
sudo nano /opt/steward/.env
```

Required (at least one LLM provider):
```
GOOGLE_API_KEY=AIza...          # Free tier
MISTRAL_API_KEY=...             # Free tier
GROQ_API_KEY=gsk_...            # Free tier
```

Federation (already set by setup script):
```
STEWARD_FEDERATION_DIR=/opt/steward/federation
```

Optional (agent-internet integration):
```
STEWARD_AGENT_INTERNET_BASE_URL=https://your-lotus-endpoint
STEWARD_AGENT_INTERNET_TOKEN=...
```

## Step 3: Start the Daemon

```bash
sudo systemctl enable --now steward
journalctl -u steward -f
```

The daemon:
- Boots once (5s), stays alive forever
- Cetana heartbeat drives 4-phase work cycle
- DHARMA: git pull → read inbound federation messages
- KARMA: dispatch tasks (deterministic + LLM when needed)
- MOKSHA: flush outbound → git push (throttled to 5-min intervals)
- Graceful shutdown on SIGTERM (Hebbian weights saved)

## Verification

```bash
# Check daemon status
sudo systemctl status steward

# Watch federation activity
journalctl -u steward -f | grep -i 'federation\|nadi\|karma\|delegate'

# Simulate a peer heartbeat (from another machine)
cd /opt/steward/federation
echo '[{"source":"peer-test","target":"steward","operation":"heartbeat","payload":{"agent_id":"test-001","health":0.9}}]' > nadi_outbox.json
git add . && git commit -m "test heartbeat" && git push
# → steward picks it up on next DHARMA phase (within 5 min)

# Check peer state
cat /opt/steward/workspace/.steward/peers.json
```

## SSH Keys for Git Federation

The steward user needs SSH access to push/pull the wiki repo:

```bash
sudo -u steward ssh-keygen -t ed25519 -C "steward@$(hostname)" -N ""
cat /opt/steward/.ssh/id_ed25519.pub
# → Add this as a deploy key on the GitHub wiki repo (with write access)
```

## Multiple Nodes

Each steward node is independent. They share state via the wiki repo:

```
Node A (steward)     ──push/pull──→  wiki.git  ←──push/pull──  Node B (agent-city)
                                        ↑
Node C (agent-internet)  ──push/pull────┘
```

Git handles merge conflicts via the retry loop (pull-rebase-push, max 3 attempts).
Heartbeats are throttled to 5-minute intervals to prevent git history bloat.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No LLM provider` | Missing API keys | Edit `/opt/steward/.env` |
| `git push rejected` | Race condition | Automatic retry (check logs) |
| `No federation transport` | `STEWARD_FEDERATION_DIR` not set | Set in `.env` |
| `GitNadiSync: not a git repo` | Federation dir not cloned | Run `setup-node.sh` with wiki URL |
| `Circuit breaker suspended` | 3 consecutive fix failures | Clears after 5 min cooldown |
